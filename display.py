from machine import Pin, I2C
import ssd1306, time

time.sleep(0.1) # Wait for USB to become ready

# I2C setup: using I2C1 with GP2 (SDA) and GP3 (SCL)
i2c = I2C(1, scl=Pin(3), sda=Pin(2), freq=400000)

# Scan for devices
devices = i2c.scan()
if devices:
    print("I2C devices found:", [hex(dev) for dev in devices])
else:
    print("No I2C devices found")

# Initialize display (most SSD1306 are 128x64, some are 128x32)
oled_width = 128
oled_height = 64
oled = ssd1306.SSD1306_I2C(oled_width, oled_height, i2c)

# Clear the display
oled.fill(0)

# Show some text
oled.text('Hi! I display things :)', 0, 0)

# Update the display
oled.show()

