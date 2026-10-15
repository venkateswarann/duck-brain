"""
High-performance Raspberry Pi Driver for GC9A01 round LCD displays.
Optimized for 60 MHz SPI and partial window (dirty rectangle) updates.
"""

import time
import spidev
import numpy as np

try:
    import RPi.GPIO as GPIO
except ImportError:
    import RPi.GPIO as GPIO  # Or lgpio/gpiod fallback if configured

WIDTH = 240
HEIGHT = 240

# GC9A01 Commands
CMD_CASET = 0x2A
CMD_RASET = 0x2B
CMD_RAMWR = 0x2C
CMD_SLPOUT = 0x11
CMD_DISPON = 0x29
CMD_MADCTL = 0x36
CMD_COLMOD = 0x3A


class GC9A01:
    def __init__(self, spi_bus=0, spi_device=0, dc_pin=9, rst_pin=25, speed_hz=60000000):
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        self.speed_hz = speed_hz

        # Initialize GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.dc_pin, GPIO.OUT)
        if self.rst_pin is not None:
            GPIO.setup(self.rst_pin, GPIO.OUT)

        # Initialize SPI at max speed (default 60 MHz)
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = self.speed_hz
        self.spi.mode = 0

        self.reset()
        self._init_display()

    def reset(self):
        """Hardware reset of the display controller."""
        if self.rst_pin is not None:
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.01)
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.02)
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.12)

    def write_cmd(self, cmd):
        """Send a single byte command."""
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])

    def write_data(self, data):
        """Send raw data buffer."""
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(data, (bytes, bytearray, memoryview)):
            self.spi.writebytes2(data)
        else:
            self.spi.writebytes(data)

    def _init_display(self):
        """Standard GC9A01 initialization sequence."""
        self.write_cmd(0xEF)
        self.write_cmd(0xEB)
        self.write_data([0x14])
        self.write_cmd(0xFE)
        self.write_cmd(0xEF)
        self.write_cmd(0xEB)
        self.write_data([0x14])
        self.write_cmd(0x84)
        self.write_data([0x40])
        self.write_cmd(0x85)
        self.write_data([0xFF])
        self.write_cmd(0x86)
        self.write_data([0xFF])
        self.write_cmd(0x87)
        self.write_data([0xFF])
        self.write_cmd(0x88)
        self.write_data([0x0A])
        self.write_cmd(0x89)
        self.write_data([0x21])
        self.write_cmd(0x8A)
        self.write_data([0x00])
        self.write_cmd(0x8B)
        self.write_data([0x80])
        self.write_cmd(0x8C)
        self.write_data([0x01])
        self.write_cmd(0x8D)
        self.write_data([0x01])
        self.write_cmd(0x8E)
        self.write_data([0xFF])
        self.write_cmd(0x8F)
        self.write_data([0xFF])
        self.write_cmd(0xB6)
        self.write_data([0x00, 0x00])
        self.write_cmd(CMD_MADCTL)
        self.write_data([0x08])  # BGR format default
        self.write_cmd(CMD_COLMOD)
        self.write_data([0x05])  # 16-bit RGB565
        self.write_cmd(0x90)
        self.write_data([0x08, 0x08, 0x08, 0x08])
        self.write_cmd(0xBD)
        self.write_data([0x06])
        self.write_cmd(0xBC)
        self.write_data([0x00])
        self.write_cmd(0xFF)
        self.write_data([0x60, 0x01, 0x04])
        self.write_cmd(0xC3)
        self.write_data([0x13])
        self.write_cmd(0xC4)
        self.write_data([0x13])
        self.write_cmd(0xC9)
        self.write_data([0x22])
        self.write_cmd(0xBE)
        self.write_data([0x11])
        self.write_cmd(0xE1)
        self.write_data([0x10, 0x0E])
        self.write_cmd(0xDF)
        self.write_data([0x21, 0x0C, 0x02])
        self.write_cmd(0xF0)
        self.write_data([0x45, 0x09, 0x08, 0x08, 0x26, 0x2A])
        self.write_cmd(0xF1)
        self.write_data([0x43, 0x70, 0x72, 0x36, 0x37, 0x6F])
        self.write_cmd(0xF2)
        self.write_data([0x45, 0x09, 0x08, 0x08, 0x26, 0x2A])
        self.write_cmd(0xF3)
        self.write_data([0x43, 0x70, 0x72, 0x36, 0x37, 0x6F])
        self.write_cmd(0xED)
        self.write_data([0x1B, 0x0B])
        self.write_cmd(0xAE)
        self.write_data([0x77])
        self.write_cmd(0xCD)
        self.write_data([0x63])
        self.write_cmd(0x70)
        self.write_data([0x07, 0x07, 0x04, 0x0E, 0x0F, 0x09, 0x07, 0x08, 0x03])
        self.write_cmd(0xE8)
        self.write_data([0x34])
        self.write_cmd(0x62)
        self.write_data([0x18, 0x0D, 0x71, 0xED, 0x70, 0x70, 0x18, 0x0F, 0x71, 0xEF, 0x70, 0x70])
        self.write_cmd(0x63)
        self.write_data([0x18, 0x11, 0x71, 0xF1, 0x70, 0x70, 0x18, 0x13, 0x71, 0xF3, 0x70, 0x70])
        self.write_cmd(0x64)
        self.write_data([0x28, 0x29, 0xF1, 0x01, 0xF1, 0x00, 0x07])
        self.write_cmd(0x66)
        self.write_data([0x3C, 0x00, 0xCD, 0x67, 0x45, 0x45, 0x10, 0x00, 0x00, 0x00])
        self.write_cmd(0x67)
        self.write_data([0x00, 0x3C, 0x00, 0x00, 0x00, 0x01, 0x54, 0x10, 0x32, 0x98])
        self.write_cmd(0x74)
        self.write_data([0x10, 0x85, 0x80, 0x00, 0x00, 0x4E, 0x00])
        self.write_cmd(0x98)
        self.write_data([0x3E, 0x07])
        self.write_cmd(0x35)
        self.write_cmd(0x21)
        self.write_cmd(CMD_SLPOUT)
        time.sleep(0.12)
        self.write_cmd(CMD_DISPON)
        time.sleep(0.02)

    def set_window(self, x0, y0, x1, y1):
        """Set the active drawing rectangle boundary."""
        self.write_cmd(CMD_CASET)
        self.write_data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        self.write_cmd(CMD_RASET)
        self.write_data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        self.write_cmd(CMD_RAMWR)

    def image(self, img):
        """Draw full 240x240 frame using optimized NumPy conversion."""
        self.set_window(0, 0, WIDTH - 1, HEIGHT - 1)
        arr = np.asarray(img.convert("RGB"), dtype=np.uint16)
        # Convert RGB888 -> RGB565
        rgb565 = ((arr[:, :, 0] & 0xF8) << 8) | ((arr[:, :, 1] & 0xFC) << 3) | (arr[:, :, 2] >> 3)
        # Big-endian byte swapping for SPI
        buf = np.empty((HEIGHT, WIDTH, 2), dtype=np.uint8)
        buf[:, :, 0] = rgb565 >> 8
        buf[:, :, 1] = rgb565 & 0xFF
        self.write_data(buf.tobytes())

    def update_partial(self, img, x, y):
        """Send only a dirty rectangle patch to the display."""
        w, h = img.size
        if w <= 0 or h <= 0:
            return

        x1 = min(WIDTH - 1, x + w - 1)
        y1 = min(HEIGHT - 1, y + h - 1)

        self.set_window(x, y, x1, y1)
        arr = np.asarray(img.convert("RGB"), dtype=np.uint16)
        rgb565 = ((arr[:, :, 0] & 0xF8) << 8) | ((arr[:, :, 1] & 0xFC) << 3) | (arr[:, :, 2] >> 3)

        buf = np.empty((h, w, 2), dtype=np.uint8)
        buf[:, :, 0] = rgb565 >> 8
        buf[:, :, 1] = rgb565 & 0xFF
        self.write_data(buf.tobytes())

    def cleanup(self):
        """Graceful shutdown."""
        try:
            self.spi.close()
            GPIO.cleanup([self.dc_pin, self.rst_pin])
        except Exception:
            pass
