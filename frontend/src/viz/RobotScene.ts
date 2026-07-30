import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import URDFLoader from "urdf-loader";
import type { URDFJoint, URDFRobot } from "urdf-loader";

export interface JointInfo {
  name: string;
  type: string;
  lower: number;
  upper: number;
  axis: [number, number, number];
}

export interface SceneStats {
  meshes: number;
  triangles: number;
  fps: number;
  height: number;
}

export type ViewPreset = "iso" | "front" | "side" | "top";

export interface RobotSceneOptions {
  canvas: HTMLCanvasElement;
  urdfUrl: string;
  /** Base URL that `package://` mesh references resolve against. */
  assetBase: string;
  onReady?: (joints: JointInfo[], stats: SceneStats) => void;
  onError?: (message: string) => void;
  onProgress?: (loaded: number, total: number) => void;
}

/**
 * A MuJoCo/RViz-style viewport for a URDF robot.
 *
 * Conventions worth knowing:
 *  - The world is Z-up, matching URDF and MuJoCo rather than three.js's Y-up
 *    default. Everything follows from setting the camera's up vector.
 *  - Meshes are used at their native scale. The Open Duck Mini description is
 *    authored in metres, so no scaling is applied anywhere; a mismatch here is
 *    an asset problem to fix in assets/, not something to paper over with a
 *    scale factor (scaling the root would shrink joint offsets too and collapse
 *    the model into overlapping parts).
 */
export class RobotScene {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly grid: THREE.GridHelper;
  private readonly floor: THREE.Mesh;
  private readonly worldAxes: THREE.AxesHelper;
  private readonly jointFrames = new THREE.Group();
  private readonly resizeObserver: ResizeObserver;
  private readonly opts: RobotSceneOptions;

  private robot: URDFRobot | null = null;
  private frameId = 0;
  private disposed = false;
  private baseOffsetZ = 0;
  private robotRadius = 0.5;
  private robotCenter = new THREE.Vector3(0, 0, 0.15);

  private wireframe = false;
  private lastFrameTime = performance.now();
  private fps = 0;
  private stats: SceneStats = { meshes: 0, triangles: 0, fps: 0, height: 0 };

  constructor(opts: RobotSceneOptions) {
    this.opts = opts;
    const canvas = opts.canvas;
    const { clientWidth, clientHeight } = this.sizeOf(canvas);

    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(clientWidth, clientHeight, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1018);
    this.scene.fog = new THREE.Fog(0x0b1018, 3, 12);

    this.camera = new THREE.PerspectiveCamera(45, clientWidth / clientHeight, 0.01, 100);
    // Z-up world, as in MuJoCo and RViz.
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(0.7, -0.7, 0.5);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.screenSpacePanning = true;
    this.controls.minDistance = 0.08;
    this.controls.maxDistance = 15;
    this.controls.target.set(0, 0, 0.15);

    this.scene.add(new THREE.HemisphereLight(0xbcd4ff, 0x20262e, 1.1));

    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(1.2, -1.4, 2.0);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = 8;
    const s = 0.8;
    key.shadow.camera.left = -s;
    key.shadow.camera.right = s;
    key.shadow.camera.top = s;
    key.shadow.camera.bottom = -s;
    key.shadow.bias = -0.0005;
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0x6ea8ff, 0.5);
    fill.position.set(-1.5, 1.0, 0.6);
    this.scene.add(fill);

    // GridHelper lies in XZ; rotate it into the XY ground plane for a Z-up world.
    this.grid = new THREE.GridHelper(4, 40, 0x2f4a63, 0x1a2734);
    this.grid.rotation.x = Math.PI / 2;
    this.scene.add(this.grid);

    this.floor = new THREE.Mesh(
      new THREE.PlaneGeometry(4, 4),
      new THREE.ShadowMaterial({ opacity: 0.35 })
    );
    this.floor.receiveShadow = true;
    this.floor.position.z = -0.001;
    this.scene.add(this.floor);

    this.worldAxes = new THREE.AxesHelper(0.12);
    this.scene.add(this.worldAxes);

    this.jointFrames.visible = false;
    this.scene.add(this.jointFrames);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    if (canvas.parentElement) this.resizeObserver.observe(canvas.parentElement);

    this.loadRobot();
    this.animate();
  }

  private sizeOf(canvas: HTMLCanvasElement) {
    const parent = canvas.parentElement;
    return {
      clientWidth: Math.max(parent?.clientWidth || canvas.clientWidth || 640, 1),
      clientHeight: Math.max(parent?.clientHeight || canvas.clientHeight || 480, 1),
    };
  }

  private loadRobot() {
    const manager = new THREE.LoadingManager();
    const loader = new URDFLoader(manager);

    // `package:///foo.stl` resolves with an empty package name, so every mesh
    // maps onto the backend's asset endpoint.
    loader.packages = () => this.opts.assetBase;
    loader.parseVisual = true;
    loader.parseCollision = true;

    const failed: string[] = [];
    loader.loadMeshCb = (path, mgr, done) => {
      new STLLoader(mgr).load(
        path,
        (geometry) => {
          geometry.computeVertexNormals();
          // The loader assigns the URDF-declared material to the returned mesh.
          done(new THREE.Mesh(geometry));
        },
        undefined,
        (err) => {
          failed.push(path.split("/").pop() || path);
          // An error argument makes the loader skip the placeholder object.
          done(new THREE.Object3D(), err as Error);
        }
      );
    };

    manager.onProgress = (_url, loaded, total) => this.opts.onProgress?.(loaded, total);

    manager.onLoad = () => {
      if (this.disposed || !this.robot) return;
      this.finalizeRobot();
      if (failed.length) {
        this.opts.onError?.(`${failed.length} mesh(es) failed to load: ${failed.slice(0, 4).join(", ")}`);
      }
      this.opts.onReady?.(this.getJoints(), this.stats);
    };

    loader.load(
      this.opts.urdfUrl,
      (robot) => {
        if (this.disposed) return;
        this.robot = robot;
        this.scene.add(robot);
      },
      undefined,
      (err) => this.opts.onError?.(`Failed to load URDF: ${(err as Error)?.message || err}`)
    );
  }

  /** Convert materials, hide colliders, stand the robot on the floor, frame it. */
  private finalizeRobot() {
    const robot = this.robot;
    if (!robot) return;

    const converted = new Map<THREE.Material, THREE.MeshStandardMaterial>();
    let meshes = 0;
    let triangles = 0;

    robot.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh) return;

      const inCollider = this.isUnderCollider(mesh);
      mesh.castShadow = !inCollider;
      mesh.receiveShadow = !inCollider;

      const source = mesh.material as THREE.Material;
      if (source && !Array.isArray(source)) {
        let next = converted.get(source);
        if (!next) {
          const color =
            (source as THREE.MeshPhongMaterial).color?.clone() ?? new THREE.Color(0xd6dde6);
          next = new THREE.MeshStandardMaterial({
            color,
            roughness: 0.55,
            metalness: 0.15,
            transparent: (source as THREE.MeshPhongMaterial).opacity < 1,
            opacity: (source as THREE.MeshPhongMaterial).opacity ?? 1,
          });
          converted.set(source, next);
        }
        mesh.material = next;
      }

      if (!inCollider) {
        meshes += 1;
        const index = mesh.geometry?.index;
        const position = mesh.geometry?.getAttribute("position");
        triangles += index ? index.count / 3 : position ? position.count / 3 : 0;
      }
    });

    // Collision geometry duplicates the visuals; start with only visuals shown.
    this.setShowCollision(false);

    // Build joint frame axes once the tree exists.
    this.jointFrames.clear();
    Object.values(robot.joints).forEach((joint) => {
      const axes = new THREE.AxesHelper(0.03);
      joint.add(axes);
    });

    // Rest the feet on the grid instead of letting the model float or sink.
    robot.position.z = 0;
    robot.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(robot);
    this.baseOffsetZ = -box.min.z;
    robot.position.z = this.baseOffsetZ;
    robot.updateMatrixWorld(true);

    const framed = new THREE.Box3().setFromObject(robot);
    const size = framed.getSize(new THREE.Vector3());
    this.robotCenter = framed.getCenter(new THREE.Vector3());
    this.robotRadius = Math.max(size.x, size.y, size.z, 0.1);

    this.stats = {
      meshes,
      triangles: Math.round(triangles),
      fps: 0,
      height: size.z,
    };

    this.setView("iso");
  }

  private isUnderCollider(obj: THREE.Object3D): boolean {
    let node: THREE.Object3D | null = obj;
    while (node) {
      if ((node as unknown as { isURDFCollider?: boolean }).isURDFCollider) return true;
      node = node.parent;
    }
    return false;
  }

  private animate = () => {
    if (this.disposed) return;
    this.frameId = requestAnimationFrame(this.animate);

    const now = performance.now();
    const dt = now - this.lastFrameTime;
    this.lastFrameTime = now;
    if (dt > 0) this.fps = this.fps * 0.9 + (1000 / dt) * 0.1;

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  private resize() {
    if (this.disposed) return;
    const { clientWidth, clientHeight } = this.sizeOf(this.renderer.domElement as HTMLCanvasElement);
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(clientWidth, clientHeight, false);
  }

  // --- public API -----------------------------------------------------------

  getJoints(): JointInfo[] {
    if (!this.robot) return [];
    return Object.entries(this.robot.joints)
      .filter(([, j]) => j.jointType !== "fixed")
      .map(([name, j]) => {
        const joint = j as URDFJoint;
        const continuous = joint.jointType === "continuous";
        return {
          name,
          type: joint.jointType,
          lower: continuous ? -Math.PI : Number(joint.limit?.lower ?? -Math.PI),
          upper: continuous ? Math.PI : Number(joint.limit?.upper ?? Math.PI),
          axis: [joint.axis?.x ?? 0, joint.axis?.y ?? 0, joint.axis?.z ?? 1] as [number, number, number],
        };
      });
  }

  setJointValues(values: Record<string, number>) {
    if (!this.robot) return;
    Object.entries(values).forEach(([name, value]) => {
      if (Number.isFinite(value) && this.robot?.joints[name]) {
        this.robot.setJointValue(name, value);
      }
    });
  }

  getJointValues(): Record<string, number> {
    if (!this.robot) return {};
    const out: Record<string, number> = {};
    Object.entries(this.robot.joints).forEach(([name, joint]) => {
      if (joint.jointType !== "fixed") out[name] = Number(joint.angle) || 0;
    });
    return out;
  }

  setWireframe(on: boolean) {
    this.wireframe = on;
    this.robot?.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mat && !Array.isArray(mat)) mat.wireframe = on;
    });
  }

  setShowVisual(on: boolean) {
    this.robot?.traverse((obj) => {
      if ((obj as unknown as { isURDFVisual?: boolean }).isURDFVisual) obj.visible = on;
    });
  }

  setShowCollision(on: boolean) {
    this.robot?.traverse((obj) => {
      if ((obj as unknown as { isURDFCollider?: boolean }).isURDFCollider) {
        obj.visible = on;
        obj.traverse((child) => {
          const mesh = child as THREE.Mesh;
          if (!mesh.isMesh) return;
          const mat = mesh.material as THREE.MeshStandardMaterial;
          if (mat && !Array.isArray(mat)) {
            mat.wireframe = true;
            mat.transparent = true;
            mat.opacity = 0.35;
            mat.color = new THREE.Color(0x3dd68c);
          }
        });
      }
    });
  }

  setShowGrid(on: boolean) {
    this.grid.visible = on;
    this.floor.visible = on;
    this.worldAxes.visible = on;
  }

  setShowJointFrames(on: boolean) {
    if (!this.robot) return;
    Object.values(this.robot.joints).forEach((joint) => {
      joint.children.forEach((child) => {
        if ((child as THREE.AxesHelper).isObject3D && child.type === "AxesHelper") {
          child.visible = on;
        }
      });
    });
  }

  setView(preset: ViewPreset) {
    const c = this.robotCenter;
    const d = this.robotRadius * 1.9;
    const positions: Record<ViewPreset, [number, number, number]> = {
      iso: [c.x + d * 0.75, c.y - d * 0.75, c.z + d * 0.55],
      front: [c.x, c.y - d, c.z],
      side: [c.x + d, c.y, c.z],
      top: [c.x, c.y - 0.001, c.z + d],
    };
    const [x, y, z] = positions[preset];
    this.camera.position.set(x, y, z);
    this.controls.target.copy(c);
    this.controls.update();
  }

  getStats(): SceneStats {
    return { ...this.stats, fps: Math.round(this.fps) };
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frameId);
    this.resizeObserver.disconnect();
    this.controls.dispose();

    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.geometry?.dispose();
        const mat = mesh.material;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose();
      }
    });
    this.scene.clear();
    this.renderer.dispose();
  }
}
