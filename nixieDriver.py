import RPi.GPIO as GPIO
import pigpio
import time, datetime
import os, sys, signal, subprocess, threading
import math

# constants

# PWM frequency
fPWM  = 200
# PWM duty cycle
dcPWM = 100.0

# GPIO 13, pin 33, PWM1
pinOE     = 13
# GPIO 12, pin 32, PWM0
pinStrobe = 12
# GPIO 16, pin 23
pinClock  = 16
# GPIO 15, pin 22
pinData   = 15
# all pins to drive
pins = (pinStrobe, pinClock, pinData)

# digits with decimal not connected, hhmmss, 0-indexed
digitNoDecimal = (1, 3)

# number of bits in shift register
nBitsRegister = 64
# clock rate for shift register
fClock = nBitsRegister * 4
tClock = 1 / float(fClock)

# shared variable that gets updated by checkPPS in a separate thread
global bPPS
bPPS = False
# shared variable to stop threads
bStopThreads = False

# local functions

def signal_handler(sig, frame):
  # clean up and exit
  print("Cleaning up.")
  global bStopThreads
  bStopThreads = True
  stopDriver()
  print("Exiting.")
  sys.exit(0)

def initDriver():
  GPIO.setmode(GPIO.BOARD)
  for pinInit in pins:
    print("Initializing GPIO %2d."%(pinInit))
    # set up GPIO pin
    GPIO.setup(pinInit, GPIO.OUT)
    GPIO.output(pinInit, GPIO.LOW)

  print("Starting pigpiod.")
  global gpioProcess
  gpioProcess = subprocess.Popen(["sudo","pigpiod","-v"])

def stopDriver():
  print("Stopping PWM on pin %2d."%(pinOE))
  pPWM.stop()
  print("Stopping pigpiod.")
  gpioProcess.terminate()
  gpioProcess.wait()
  print("Freeing GPIO.")
  GPIO.cleanup()

def decodeDigit(num, bDot):
  # return 10-digit binary representation of digit

  if num == 1:
    bin = (bDot, True,  False, False, False, False, False, False, False, False, False)
  elif num == 2:
    bin = (bDot, False, True,  False, False, False, False, False, False, False, False)
  elif num == 3:
    bin = (bDot, False, False, True,  False, False, False, False, False, False, False)
  elif num == 4:
    bin = (bDot, False, False, False, True,  False, False, False, False, False, False)
  elif num == 5:
    bin = (bDot, False, False, False, False, True,  False, False, False, False, False)
  elif num == 6:
    bin = (bDot, False, False, False, False, False, True,  False, False, False, False)
  elif num == 7:
    bin = (bDot, False, False, False, False, False, False, True,  False, False, False)
  elif num == 8:
    bin = (bDot, False, False, False, False, False, False, False, True,  False, False)
  elif num == 9:
    bin = (bDot, False, False, False, False, False, False, False, False, True,  False)
  elif num == 0:
    bin = (bDot, False, False, False, False, False, False, False, False, False, True )
  else:
    bin = (bDot, False, False, False, False, False, False, False, False, False, False)
  return bin

def checkPPS():
  print("Starting PPS checking thread.")
  global bPPS
  while True:
    # look for output indicative of PPS from ppstest program
    ppsProcess = subprocess.Popen(["sudo","ppstest","/dev/pps0"], stdout=subprocess.PIPE)
    time.sleep(1.05)
    ppsProcess.terminate()
    ppsOutput = str(ppsProcess.stdout.peek())
    #ppsProcess.wait()
    bPPS = ppsOutput.find("sequence") != -1
    #print("PPS: " + str(bPPS))

    if bStopThreads:
      print("Stopping PPS checking thread.")
      ppsProcess.terminate()
      ppsProcess.wait()
      break

def timeToBin():
  # return binary tuple of current time for nixie tubes
  # offset by 1 second in the future for the next strobe
  t = datetime.datetime.now() + datetime.timedelta(0,1)

  h = t.hour
  m = t.minute
  s = t.second

  PM = h > 12
  h = h%12
  if h == 0:
    h = 12

  # value to display for each nixie digit
  hhmmss = (math.floor(h/10),  h%10, math.floor(m/10),  m%10, math.floor(s/10),  s%10)
  bDot   = (              PM, False,             True, False,             True,  bPPS)

  bin = ()
  for iDigit in range(len(hhmmss)):
    digit = hhmmss[iDigit]
    # don't display leading 0 in hour
    if iDigit == 0 and digit == 0:
      digit = float("nan")

    binDigit = decodeDigit(digit, bDot[iDigit])

    # remove decimal in digits where it is not wired
    if digit in digitNoDecimal:
      binDigit = binDigit[1:]

    # concatenate digits
    bin = bin + binDigit
  return bin

def updateShiftRegister():
  bin = timeToBin()

  t = datetime.datetime.now() + datetime.timedelta(0,1)
  print("Updating shift register with %2d:%02d:%02d"%(t.hour, t.minute, t.second))

  tStartBin = time.process_time_ns()

  for bit in bin:
    tStartBit = time.process_time_ns()

    # set clock high
    GPIO.output(pinClock, GPIO.HIGH)

    # wait 1/4 cycle
    time.sleep((tClock * 0.25) - (float(tStartBit - time.process_time_ns())*1E-9))

    # set data
    GPIO.output(pinData, bit)

    # wait 1/4 cycle
    time.sleep((tClock * 0.75) - (float(tStartBit - time.process_time_ns())*1E-9))

    # set clock low
    GPIO.output(pinClock, GPIO.LOW)

    # wait 1/4 cycle
    time.sleep((tClock * 1.00) - (float(tStartBit - time.process_time_ns())*1E-9))




# main function

# set up signal handlers
signal.signal(signal.SIGINT,  signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# start PPS checking
threadPPS = threading.Thread(target = checkPPS)
threadPPS.start()

# initialize pins
initDriver()

# set up strobe output
pPWM = pigpio.pi()
pPWM.hardware_PWM(pinOE, fPWM, round(10000 * dcPWM))
print("PWM (f = %d Hz, dc = %.1f %%) starting on pin %2d."%(fPWM, dcPWM, pinOE))

# main loop

#synchronize to wall clock
time.sleep(1 - time.time()%1)

while True:
  tStartSecond = time.time()

  # wait until 0.25 second
  time.sleep(0.25 - time.time()%1)

  # lower strobe
  if GPIO.gpio_function(pinStrobe) == GPIO.OUT:
    GPIO.output(pinStrobe, GPIO.LOW)

  # update shift register
  updateShiftRegister()

  # handle inconsistent PPS behavior
  if bPPS:
    if GPIO.gpio_function(pinStrobe) == GPIO.OUT:
      # disable strobe output when PPS is valid
      GPIO.setup(pinStrobe, GPIO.IN)

  # anti-poisoning routine

  # wait until next second
  time.sleep(1 - time.time()%1)

  # strobe output
  if GPIO.gpio_function(pinStrobe) == GPIO.OUT:
    print("Strobing output.")
    GPIO.output(pinStrobe, GPIO.HIGH)
