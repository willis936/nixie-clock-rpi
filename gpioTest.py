import RPi.GPIO as GPIO
import time

# GPIO pin to drive
# GPIO 15, pin 22
pinDrive = 15

# set up GPIO pin
GPIO.setmode(GPIO.BOARD)
GPIO.setup(pinDrive, GPIO.OUT)


# set output to high for 5 seconds then low for 5 seconds
timeSet = 3
print("Setting pin " + str(pinDrive) + " HIGH for " + str(timeSet) + " seconds.")
GPIO.output(pinDrive, GPIO.HIGH)
time.sleep(timeSet)

print("Setting pin " + str(pinDrive) + "  LOW for " + str(timeSet) + " seconds.")
GPIO.output(pinDrive, GPIO.LOW)
time.sleep(timeSet)

# clean up and exit
GPIO.cleanup()
exit()
