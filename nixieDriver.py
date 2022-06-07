import RPi.GPIO as GPIO
import pigpio
import time, datetime
import os, sys, signal, subprocess, threading, gc
from contextlib import contextmanager,redirect_stderr,redirect_stdout
import math, numpy

# constants

# GPIO 13, pin 33, PWM1
pinOE     = 13
# GPIO 12, pin 32, PWM0
pinStrobe = 12
# GPIO 21, pin 40
pinClock  = 21
# GPIO 20, pin 38
pinData   = 20
# all pins to drive except ones handled by hardware timers
pins = (pinStrobe, pinClock, pinData)

# invert logical outputs (needed for level shifters)
bInvertPins = True

# digits with decimal not connected, hhmmss, 0-indexed
digitNoDecimal = (1, 3)


# PWM frequency
fPWM  = 200
# PWM duty cycle
dcPWM = 100.0
if bInvertPins:
  dcPWM = 100.0 - dcPWM
# one billion
cBillion = int(1E9)
# offset (seconds) to strobe prior to start-of-second
tPreEmpt = -56e-3
# offset (seconds) for python self-time
tCode = 3E-6
# minimum window time
tMinWin = int(tCode * cBillion)
# offset (seconds) from start-of-second to start busy-wait
tBusyWindow = 20E-3

# busy waiter threshold (nanoseconds)
tBusyThresh = int((1 - tCode - tPreEmpt) * cBillion)
# handle delay rather than pre-emption
bDelayPPS = tBusyThresh > cBillion - tMinWin
if bDelayPPS:
  tBusyThresh2 = tBusyThresh - cBillion
  tBusyThresh  = cBillion - tMinWin
# max number of samples for stats
nMaxStats = int(60 * 60 * 24)


# enable anti-poisoning routine
bAntiPoison = True

# number of bits in shift register
nBitsRegister = 64
# clock rate for shift register
fClock = nBitsRegister * 4
tClock = 1 / float(fClock)

# shared variable that gets updated by checkPPSIn in a separate thread
global bPPSIn
bPPSIn = False
# shared variable to stop threads
bStopThreads = False

# shared variable to track timing error
global tErr
tErr = []


# handle inverted clock pin driving
if bInvertPins:
  clkHi = GPIO.LOW
  clkLo = GPIO.HIGH
else:
  clkHi = GPIO.HIGH
  clkLo = GPIO.LOW

# local functions

def signal_handler(sig, frame):
  # report timing error stats
  tErrArr = numpy.asarray(tErr)
  if tErrArr.size > 0:
    print("Timing error stats, us")
    print("N: %6d, mean: %7.3f, std: %7.3f"%(tErrArr.size, tErrArr.mean(), tErrArr.std()))
    print("max: %7.3f, min: %7.3f"%(tErrArr.max(), tErrArr.min()))

  # clean up and exit
  print("Cleaning up.")
  global bStopThreads
  bStopThreads = True
  stopDriver()
  print("Exiting.")
  sys.exit(0)

@contextmanager
def suppress_stdout_stderr():
  """A context manager that redirects stdout and stderr to devnull"""
  with open(os.devnull, 'w') as fnull:
    with redirect_stderr(fnull) as err, redirect_stdout(fnull) as out:
      yield (err, out)

def initDriver():
  waitForPigpio()
  GPIO.setmode(GPIO.BCM)
  for pinInit in pins:
    print("Initializing GPIO %2d."%(pinInit))
    # set up GPIO pin
    GPIO.setup(pinInit, GPIO.OUT, initial=bInvertPins)

def stopDriver():
  print("Stopping PWM on pin %2d."%(pinOE))
  pPWM.stop()
  print("Freeing GPIO.")
  GPIO.cleanup()

def waitForPigpio():
  # wait for pigpiod to come up
  maxTries = 200
  tSleep   = 0.01

  bKeepTrying = True
  nTries = 0
  while bKeepTrying:
    nTries += 1
    with suppress_stdout_stderr():
      bSucc = pigpio.pi().connected
    if bSucc or nTries >= maxTries:
      bKeepTrying = False
    else:
      time.sleep(tSleep)

  return bSucc

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

def checkPPSIn():
  print("Starting PPS checking thread.")
  global bPPSIn
  while not bStopThreads:
    # look for output indicative of PPS from ppstest program
    ppsInProcess = subprocess.Popen(["sudo","ppstest","/dev/pps0"], stdout=subprocess.PIPE)
    time.sleep(1.05)
    if bStopThreads:
      print("Stopping PPS checking thread.")

    ppsInProcess.terminate()
    ppsInOutput = str(ppsInProcess.stdout.peek())
    bPPSIn = ppsInOutput.find("sequence") != -1

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
    hhmmss = (math.floor(h/10),  h%10, math.floor(m/10),  m%10, math.floor(s/10),    s%10)
    bDot   = (              PM, False,             True, False,             True,  bPPSIn)

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

  # invert binary output
  if bInvertPins:
    bin = [not binTmp for binTmp in bin]

  return bin

def updateShiftRegister():
  bin = timeToBin()

  t = datetime.datetime.now() + datetime.timedelta(0,1)
  print("Updating shift register with %2d:%02d:%02d"%(t.hour, t.minute, t.second))

  tStartBin = time.process_time_ns()

  for bit in bin:
    tStartBit = time.process_time_ns()

    # set clock high
    GPIO.output(pinClock, clkHi)

    # wait 1/4 cycle
    time.sleep((tClock * 0.25) - (float(tStartBit - time.process_time_ns())*1E-9))

    # set data
    GPIO.output(pinData, bit)

    # wait 1/4 cycle
    time.sleep((tClock * 0.75) - (float(tStartBit - time.process_time_ns())*1E-9))

    # set clock low
    GPIO.output(pinClock, clkLo)

    # wait 1/4 cycle
    time.sleep((tClock * 1.00) - (float(tStartBit - time.process_time_ns())*1E-9))




# main function

# set up signal handlers
signal.signal(signal.SIGINT,  signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# start PPS In checking
threadPPSIn = threading.Thread(target = checkPPSIn)
threadPPSIn.start()

# initialize pins
initDriver()

# set up PWM Output Enable output
pPWM = pigpio.pi()
pPWM.hardware_PWM(pinOE, fPWM, round(10000 * dcPWM))
print("PWM (f = %d Hz, dc = %.1f %%) starting on pin %2d."%(fPWM, dcPWM, pinOE))

# main loop

#synchronize to wall clock
time.sleep(1 - time.time()%1)

while True:
  # wait until 0.10 second
  time.sleep(0.10 - time.time()%1 - tPreEmpt)

  # lower strobe
  GPIO.output(pinStrobe, clkLo)

  # wait until 0.25 second
  time.sleep(0.25 - time.time()%1 - tPreEmpt)

  # update shift register
  updateShiftRegister()

  # run garbage collection just before a long wait
  gc.collect()

  # wait until next second, minus busy-wait window
  time.sleep(1 - time.time()%1 - tBusyWindow)

  # busy-wait until pre-empt time
  while time.time_ns()%cBillion < tBusyThresh:
    pass
  if bDelayPPS:
    # handle delay rather than pre-emption
    bCont = True
    while bCont:
      tNow = time.time_ns()%cBillion
      bCont = tNow > (0.5 * cBillion) or tNow < tBusyThresh2

  tErrTmp = 1 - time.time()%1 - tPreEmpt
  if tErrTmp > 0.5:
    tErrTmp = 1 - tErrTmp
  tErrTmp = tErrTmp * 1E6
  while len(tErr) >= nMaxStats:
    tErr.pop(0)
  tErr.append(tErrTmp)
  print("pre-empt error: %3.3f us"%tErrTmp)

  # strobe output
  GPIO.output(pinStrobe, clkHi)

  # sleep until start of second
  tEndOfSecond = time.time()%1
  if tEndOfSecond > 0.5 and tEndOfSecond < (1 - tCode):
    time.sleep(1 - tEndOfSecond)
