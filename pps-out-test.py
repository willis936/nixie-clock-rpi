import os, sys, time, signal, subprocess, threading, gc, datetime, numpy
from queue import Queue, Empty

import asyncio

ON_POSIX = 'posix' in sys.builtin_module_names

# GPIO 12, pin 32, PWM0
pinStrobe = 12

# offset (seconds) to strobe prior to start-of-second
tPreEmpt = 30E-6

nMaxStats = 86400

global bStopThreads
bStopThreads = False

# shared variable to track timing error
global tErr
tErr = []

def enqueue_output(out, queue):
  for line in iter(out.readline, b''):
    queue.put(line.rstrip('\r\n').decode('utf-8'))
  out.close()

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
  print("Exiting.")
  sys.exit(0)

def drivePPSOut():
  print("Starting PPS driving thread.")

  #strCall = ["sudo","chrt","--rr","99","pps-out","-g",str(pinStrobe),"-e",str(round(tPreEmpt  *1E6)),"-m",str(round(0.1*1E6)),"-l","1","-s","1"]
  strCall = ["sudo","pps-out","-g",str(pinStrobe),"-e",str(round(tPreEmpt  *1E6)),"-m",str(round(0.1*1E6)),"-l","1","-s","1"]
  print(strCall)

  #ppsOutProcess = subprocess.Popen(strCall, stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
  ppsOutProcess = subprocess.Popen(strCall, stdout=subprocess.PIPE)
  

  #q = Queue()
  #t = threading.Thread(target=enqueue_output, args=(ppsOutProcess.stdout, q))
  #t.daemon = True # thread dies with the program
  #t.start()

  while True:
    # collect timing error stats
    #sys.stdout.flush()

    #outs = ppsOutProcess.communicate(timeout=0.5)
    #print(outs)

    #try:
    #  line = q.get_nowait() # or q.get(timeout=.1)
    #except Empty:
    #  print("Nada")
    #  pass
    #else: # got line
    #  # convert string to list of numbers
    #  #line = line.decode('utf-8')
    #  # valid lines have exactly 32 characters
    #  if len(line) != 33:
    #    print(len(line))
    #    #continue

    #line = ppsOutProcess.stdout.readline().decode('utf-8')
    #print(ppsOutProcess.stdout.peek())
    line = ppsOutProcess.stdout.readline().rstrip()
    #line = ppsOutProcess.communicate()
    #line = line[:-1]
    print(line)
    print(len(line))

    #for stdout_line in iter(ppsOutProcess.stdout.readline, ""):
    #  print(stdout_line)
    #line = stdout_line

    try:
      line = [int(i) for i in line.split()]
    except:
      print("Fail")
      continue
      pass
    else:
      print(len(line))
      pass

    if len(line) != 5:
      time.sleep(0.5)
      continue

    tErrTmp = line[2]
    tErrTmp = tErrTmp
    while len(tErr) >= nMaxStats:
      tErr.pop(0)
    tErr.append(tErrTmp)
    print("pre-empt error: %3.3f us"%tErrTmp)

    if bStopThreads:
      print("Stopping PPS driving thread.")
      ppsOutProcess.terminate()
      ppsOutProcess.wait()
      break

# set up signal handlers
signal.signal(signal.SIGINT,  signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# start PPS Out driving
threadPPSOut = threading.Thread(target = drivePPSOut)
threadPPSOut.start()

#synchronize to wall clock
time.sleep(1 - time.time()%1)

while True:
  print(datetime.datetime.now())
  gc.collect()
  # sleep until start of second
  time.sleep(1 - time.time()%1)
