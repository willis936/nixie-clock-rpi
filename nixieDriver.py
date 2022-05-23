import RPi.GPIO as GPIO
import pigpio
import time, datetime
import os, sys, signal, subprocess, threading, gc
import math

# constants

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


# PWM frequency
fPWM  = 200
# PWM duty cycle
dcPWM = 100.0
# offset (seconds) to strobe prior to start-of-second
tPreEmpt = 30E-6
# offset (seconds) for python self-time
tCode = 4E-6
# offset (seconds) from start-of-second to start busy-wait
tBusyWindow = 20E-3


# enable anti-poisoning routine
bAntiPoison = True

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

  #print("Starting pigpiod.")
  #global gpioProcess
  #gpioProcess = subprocess.Popen(["sudo","pigpiod","-v"])

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

  if type(num) == int and num < 10:
    # decode digit
    bin = ((False,) * (num - 1)) + (True,) + ((False,) * (10 - num))
  elif num == 0:
    # 0 is at the end
    bin = ((False,) * 9) + (True,)
  else:
    # no digit if number is invalid
    bin = (False,) * 10
  # add dot to beginning of decode
  bin = (bDot,) + bin
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
    bPPS = ppsOutput.find("sequence") != -1

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

  # anti-poisoning routine
  if bAntiPoison and h < 1 and m == 5:
    # value to display for each nixie digit
    hhmmss = (s%10,)   * 6
    bDot   = (s%3 < 1) * 6
  else:
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

# set process affinity to highest
os.nice(40)
print("Nice value of the process: %2d / %2d"%(os.nice(0), 19))

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
  # wait until 0.10 second
  time.sleep(0.10 - time.time()%1)

  # wait until 0.25 second
  time.sleep(0.25 - time.time()%1)

  # lower strobe
  GPIO.output(pinStrobe, GPIO.LOW)

  # update shift register
  updateShiftRegister()

  # run garbage collection
  gc.collect()

  # wait until next second, minus busy-wait window
  time.sleep(1 - time.time()%1 - tBusyWindow)

  # busy-wait until pre-empt time
  while True:
    if (1 - time.time()%1 <= tCode + tPreEmpt):
      break

  tErr = 1 - time.time()%1 - tPreEmpt
  if tErr > 0:
    tErr = tErr%1
  print("pre-empt error: %3.3f us"%(tErr * 1E6))

  # strobe output
  GPIO.output(pinStrobe, GPIO.HIGH)

  # sleep until start of second
  tEndOfSecond = time.time()%1
  if tEndOfSecond > 0.5 and tEndOfSecond < (1 - tCode):
    time.sleep(1 - tEndOfSecond)