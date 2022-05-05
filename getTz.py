import gpsd
from timezonefinder import TimezoneFinder
import os, time

# connect to GPS
gpsd.connect()
tf = TimezoneFinder()

# get current position and calculate timezone
packet = gpsd.get_current()
if packet.mode < 2:
  counter = 1
  counterMax = 120
  while (packet.mode < 2) and (counter <= counterMax):
    print("No GPS lock.  Waiting 1 second to try again (" + counter + " / " + counterMax + ")")
    time.sleep(1)
    packet = gpsd.get_current()
    counter += 1
latitude, longitude = packet.position()
print("Current lat, long: " + str(latitude) + ", " + str(longitude))

# set timezone
tz = tf.timezone_at(lng=longitude, lat=latitude)
print("Setting timezone to " + tz)
os.environ['TZ'] = tz

exit()
