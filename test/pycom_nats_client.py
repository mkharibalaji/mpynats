import pycom
import machine
import _thread
import gc
from network import WLAN
import mpynats

wlan = WLAN(mode=WLAN.STA)
pycom.heartbeat(False)

if not wlan.isconnected():
    wlan.connect('Test', auth=(WLAN.WPA2, 'booboo@123'), timeout=5000)
    while not wlan.isconnected():
        machine.idle() # save power while waiting
        break

def callback(msg):
    print('Received a message: %s' % msg.data)

def th_func(id, param):
    c.wait()
        
if wlan.isconnected():
    c = mpynats.Connection('nats://192.168.1.4:4222', 'swift', False, True, False, False, False, True)
    c.connect()
    c.subscribe('foochip', callback)
    _thread.start_new_thread(th_func, (1, 2))
    c.publish('foo', 'HelloWorld')
    print("Nats Server Connected!!!")
