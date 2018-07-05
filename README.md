**This repository is no longer being maintained.** - I no longer have the V2 hardware, so please fork the project and continue development.  I will provide support as best I can.

# simplisafe-rf
Protocols used by SimpliSafe (v2) devices over RF, implemented in Python.

# Introduction
Being a [SimpliSafe](https://www.simplisafe.com) customer for many years, I have found some shortcomings, and have always wanted to find a way to remedy them.  However, I had never delved into wireless communication before and wasn't tempted to start, until I came across [this article](http://blog.ioactive.com/2016/02/remotely-disabling-wireless-burglar.html) that quickly went viral.  It unveiled that the wireless communication protocol used by SimpliSafe is unencrypted, which makes some customers feel unsafe or cheated, but in my case, it allows for some relatively easy "customization" of the system.  Also inspired by [this follow-up](http://greatscottgadgets.com/2016/02-19-low-cost-simplisafe-attacks/) and [this thread](https://news.ycombinator.com/item?id=11125223), I decided it was time to give it a shot.

The aforementioned shortcomings that bothered me are as follows:
* System arms even if entry sensors are open (alarm will trigger if they open after they are closed)
    * This is atypical of security systems, as the system should be "secure" before it is armed
    * The keypad says if an entry sensor is open, but not which one, and is not obvious unless you look and wait for the message to scroll on the display
* No support for logging all sensor events, only of arm state changes or errors
* No internet-based back-up communication if the cellular link is down
* No remote notification (e-mail/text) when power is first applied (after batteries are replaced or dead)
    * This is useful for knowing when power is restored after a long outage
* Lack of ability to integrate with other home automation systems
    * This is marginally possible through their web-based API, but requires the Interactive Motoring plan; see [here](/greencoder/simplisafe-python) and [here](/searls/simplisafe) for examples

As pointed out by the articles mentioned above, reverse engineering the RF protocol used by the SimpliSafe devices was not very difficult, but the articles failed to disclose any details.  The basics of the low-level protocol can be found in the [SimpliSafe, Inc. FCC Wireless Applications](https://fccid.io/U9K) timing diagrams.  From there, all it takes it sniffing the data and doing some some decoding.  I used a Raspberry Pi and inexpensive (<$10) 315MHz and 433MHz transmitter/receiver pairs (RF hardware).  The [pigpio library](http://abyz.co.uk/rpi/pigpio/) was used for interfacing with the RF hardware.  I wrote a crude Python module (pigpio.py) that decodes/encodes the waveforms to/from bytes using [pigpio](http://abyz.me.uk/rpi/pigpio/python.html). They key module in this repository, messages.py, is what transforms the bytes to/from human-readable messages for use in applications.  The other module, devices.py, allows the user to emulate any SimpliSafe device.

It should be noted that the Raspberry Pi may not be the best selection for interfacing with the RF hardware as it does not execute in real-time. I have issues when trying to transmit messages using pigpio, as I believe interrupts may be causing errors in the bit timing.  A microcontroller or FPGA would be a better choice, but then it would need to interface with a device that could support the Python module and perform more complex functions, like interfacing with the web, databases, or home automation systems.  Therefore, these Python modules are to serve as a guide for further development.  See the [wiki](https://github.com/bggardner/simplisafe-rf/wiki) for details.

# Requirements

* Python 3
* RF Hardware supporting on-off keying (OOK)
    * 315MHz Receiver (for keypad emulation and base station message logging)
    * 315MHz Transmitter (for base station emulation)
    * 433MHz Receiver (for base station emulation and keypad/sensor message logging)
    * 433MHz Transmitter (for keypad/sensor emulation)
* Digital waveform to/from bytes mechanism (options below)
    * Raspberry Pi
        * RFUtils module (from this repo):
            * Requires `python3-pigpio` Raspbian package installed
            * Requires `pigpiod` (pigpio daemon) running
    * FPGA or Microcontroller (Arduino, etc.)
        * Requires interface to other device for Python support (possibly via SPI, etc.)

# Usage Examples

* Base stations receive 433MHz signals and transmit 315MHz signals.
* Keypads receive 315MHz signals and transmit 433MHz signals.
* Sensors (including keychain remotes) only transmit 433MHz signals.

*NOTE: This is not meant to be a script, as each code block is an individual example*
```python
#!/usr/bin/python3
from simplisafe import DeviceType
from simplisafe.devices import Keypad
from simplisafe.messages import EntrySensorMessage, MotionSensorMessage, KeychainRemoteMessage, DisarmPinRequest, BaseStationKeypadDisarmPinResponse
from simplisafe.pigpio import Transceiver

RX_315MHZ_GPIO = 17 # Connected to DATA pin of 315MHz receiver
RX_433MHZ_GPIO = 27 # Connected to DATA pin of 433MHz receiver
TX_315MHZ_GPIO = 16 # Connected to DATA pin of 315MHz transmitter
TX_433MHZ_GPIO = 20 # Connected to DATA pin of 433MHz transmitter

# 433MHz traffic monitor:
with Transceiver(rx=RX_433MHZ_GPIO) as txr:
    while True:
        msg = txr.recv() # Returns when a valid message is received and parsed
        print(str(msg))
    
# Simulated entry sensor "open":
with Transceiver(tx=TX_433MHZ_GPIO) as txr:
    sn = "123AZ" # Serial number of simulated entry sensor (must be added to base station list of sensors)
    sequence = 0x0 # Should be incremented after each send by this sensor
    event_type = EntrySensorMessage.EventType.OPEN # OPEN or CLOSED
    msg = EntrySensorMessage(sn, sequence, event_type)
    txr.send(msg)

# Simulated motion sensor "trip":
with Transceiver(tx=TX_433MHZ_GPIO) as txr:
    sn = "456JK" # Serial number of simulated motion sensor (must be added to base station list of sensors)
    sequence = 0xA # Should be incremented after each send by this sensor
    event_type = MotionSensorMessage.EventType.MOTION # HEARTBEAT or MOTION
    msg = MotionSensorMessage(sn, sequence, event_type)
    txr.send(msg)

# Simulated keychain remote "off":
with RFUtils.Transceiver(tx=TX_433MHZ_GPIO) as txr:
    sn = "789BG" # Serial number of simulated keychain (must be added to base station list of sensors)
    sequence = 0x7 # Should be incremented after each send by this sensor
    event_type = KeychainRemoteMessage.EventType.OFF # PANIC, AWAY, or OFF
    msg = KeychainRemoteMessage(sn, sequence, event_type)
    txr.send(msg)

# Simulated keypad disarm PIN request:
with RFUtils.Transceiver(tx=TX_433MHZ_GPIO) as txr:
    sn = "159MP" # Serial number of simulated keypad (must be added to base station list of sensors)
    sequence = 0x3 # Should be incremented after each send by this sensor
    pin = "1379" # Can be 4-digit string or integer
    msg = KeypadDisarmPinRequest(sn, sequence, pin)
    txr.send(msg) # Base station will respond on 315MHz with "VALID" or "INVALID"

# Simulated base station valid disarm PIN response:
with RFUtils.Transceiver(tx=TX_433MHZ_GPIO) as txr:
    kp_sn = "159MP" # Serial number of keypad that send disarm PIN request
    sequence = 0xF # Should be incremented after each send by this base station
    bs_sn = "456JK" # Serial number of simulated base station
    response_type = BaseStationKeypadDisarmPinResponse.ResponseType.VALID # VALID or INVALID
    msg = BaseStationKeypadDisarmPinResponse(kp_sn, sequence, bs_sn, resposne_type)
    txr.send(msg)
```
