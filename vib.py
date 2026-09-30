# Make the motor vibrate on 70% of power for 10 seconds.
# Then for another 10 seconds on full power with shorter intervals.
#
# Based on example from:
# https://core-electronics.com.au/courses/raspberry-pi-pico-workshop/#2.7

from machine import Pin, PWM # we need to import PWM to use PWM
import time

led = Pin("LED", Pin.OUT) # onboard LED

# intialise pin 16 as a PWM output
pwm_pin = PWM(Pin(28))

# this sets up the frequency that the pin is turned off and on (it is not duty cycle)
pwm_pin.freq(1000)

# this varaible is used to help calculate the required input from a duty cycle percentage
max = 65535

# while loop for 10 seconds:
t_end = time.time() + 10 
while time.time() < t_end:
    led.on()
    pwm_pin.duty_u16( int(0.7 * max) ) # turn on at 70%
    time.sleep(0.5)

    led.off()
    pwm_pin.duty_u16(0) # turn off
    time.sleep(0.5)

# while loop for 10 seconds:
t_end = time.time() + 10 
while time.time() < t_end:
    led.on()
    pwm_pin.duty_u16( max ) # turn on at max power
    time.sleep(0.1)

    led.off()
    pwm_pin.duty_u16(0) # turn off
    time.sleep(0.1)