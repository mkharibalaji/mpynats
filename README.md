# mpynats

A MicroPython client for [NATS.io](https://nats.io).

> Note:
    Socket KeepAlive Option is not available as of now,will be added once the feature is available in MicroPython.

Thanks to @mcuadros - pynats being ported to Micropython with minor changes

Requirements
------------

* MicroPython ~1.8.6
* [gnatsd server](https://github.com/nats-io/gnatsd)
* Any MicroPython supported PyBoard - As of now tested on [PyCom Chips](https://www.pycom.io/) running on ESP32


Usage
-----
### Basic Usage

```python
c = mpynats.Connection(verbose=True)
c.connect()

# Simple Publisher
c.publish('foo', 'Hello World!')

# Simple Subscriber
def callback(msg):
    print 'Received a message: %s' % msg.data

c.subscribe('foo', callback)

# Waiting for one msg
c.wait(count=1)

# Requests
def request_callback(msg):
    print 'Got a response for help: %s' % msg.data

c.request('help', request_callback)
c.wait(count=1)

# Unsubscribing
subscription = c.subscribe('foo', callback)
c.unsubscribe(subscription)

# Close connection
c.close()
```
Example
-----
### Basic Example
```
import machine
from network import WLAN #Pycom Library
import mpynats

wlan = WLAN(mode=WLAN.STA)
wlan.connect('Test', auth=(WLAN.WPA2, 'booboo@123'), timeout=5000)
while not wlan.isconnected():
  machine.idle() # save power while waiting
  break

if wlan.isconnected():
    c = mpynats.Connection('nats://192.168.1.4:4222', 'swift', False, True, False, False, False, True)
    c.connect()
    print("Nats Server Connected!!!")
    c.publish('foo', 'HelloWorld')
```

License
-------

MIT, see [LICENSE](LICENSE)

