from nicegui import ui
from pypot.feetech import FeetechSTS3215IO
import datetime
import asyncio

# Initialize the IO
io = FeetechSTS3215IO(
    "/dev/ttyACM0",
    baudrate=1000000,
    use_sync_read=True,
)

# Joints dictionary
joints = {
    "left_hip_yaw": 20,
    "left_hip_roll": 21,
    "left_hip_pitch": 22,
    "left_knee": 23,
    "left_ankle": 24,
    "neck_pitch": 30,
    "head_pitch": 31,
    "head_yaw": 32,
    "head_roll": 33,
    "right_hip_yaw": 10,
    "right_hip_roll": 11,
    "right_hip_pitch": 12,
    "right_knee": 13,
    "right_ankle": 14,
}

# List of joint names and IDs
joint_names = list(joints.keys())
joint_ids = list(joints.values())

# Function to get voltages
def get_voltages():
    raw_voltages = io.get_present_voltage(joint_ids)
    return [round(v * 0.1, 2) for v in raw_voltages]

# UI setup
async def main():
    ui.context.client.request.max_content_length = 100 * 1024 * 1024  # Optional, if needed

    # Dark mode for a modern look
    ui.context.client.dark = True

    # Header with time
    with ui.row().classes('w-full justify-between items-center p-4 bg-primary text-white'):
        ui.label('Joint Voltage Dashboard').classes('text-2xl font-bold')
        time_label = ui.label().classes('text-lg')

    # Update time every second
    async def update_time():
        while True:
            time_label.text = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            await asyncio.sleep(1)

    ui.timer(1, lambda: time_label.set_text(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    # Container for joints
    with ui.column().classes('w-full items-center'):
        # Group into cards for beauty
        with ui.card().classes('w-3/4 my-4 shadow-lg'):
            ui.label('Joint Voltages').classes('text-xl font-semibold mb-4 text-center')

            # Progress bars
            progress_bars = []
            value_labels = []

            for name in joint_names:
                with ui.row().classes('w-full justify-between items-center mb-2'):
                    ui.label(name.capitalize().replace('_', ' ')).classes('w-1/4 text-lg')
                    progress = ui.linear_progress(0, show_value=False).classes('w-1/2')
                    value_label = ui.label('0.00 V').classes('w-1/4 text-right')
                    progress_bars.append(progress)
                    value_labels.append(value_label)

    # Update voltages every 2 seconds
    def update_voltages():
        voltages = get_voltages()
        for i, (progress, value_label) in enumerate(zip(progress_bars, value_labels)):
            voltage = voltages[i]
            normalized = voltage / 8.5
            color = 'green' if voltage >= 6.6 else 'red'
            progress.value = normalized
            progress.classes(remove='bg-red bg-green')  # Reset classes
            progress.classes(add=f'bg-{color}')
            value_label.text = f'{voltage} V'

    ui.timer(2, update_voltages)

    # Initial update
    update_voltages()

ui.run(title='Joint Voltage Dashboard', dark=True)
