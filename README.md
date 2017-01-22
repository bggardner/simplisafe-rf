# simplisafe-rf
The application-layer protocol used by SimpliSafe devices over RF.

# Introduction
Being a [SimpliSafe](https://www.simplisafe.com) customer for many years, I have found some shortcomings, and have always wanted to find a way to remedy them.  However, I had never delved into wireless communication before and wasn't tempted to start, until I came across [this article](http://blog.ioactive.com/2016/02/remotely-disabling-wireless-burglar.html) that quickly went viral.  Also inspired by [this follow-up](http://greatscottgadgets.com/2016/02-19-low-cost-simplisafe-attacks/) and [this thread](https://news.ycombinator.com/item?id=11125223), I decided it was time to git it a shot.

The unencrypted communication didn't bother me very much, as the system is inexpensive and "good enough" for most consumers.  That being said, the aforementioned shortcomings that bothered me are as follows:
* System arms even if entry sensors are open (alarm will trigger if they open after they are closed)
    * This is atypical of security systems, as the system should be "secure" before it is armed
    * The keypad says if an entry sensor if open, but not which one, and is not obvious unless you look and wait for the message to scroll on the display
* No log of all sensor events, only of arm state changes or errors
* No internet-based back-up communication if the cellular link is down
* No remote notification (e-mail/text) when power is first applied (after batteries are replaced or dead)
    * This would be useful for knowing power was restored after a long outage
* Lack of ability to integrate with other home automation systems
    * This is marginally possible through their web-based API, but requires the Interactive Motoring plan; see [here](/greencoder/simplisafe-python) and [here](/searls/simplisafe)

As pointed out by the articles mentioned above, reverse engineering the RF protocol used by the SimpliSafe devices was not very difficult, but the articles failed to disclose any details.  The basics of the low-level protocol can be seen in the [SimpliSafe, Inc. FCC Wireless Applications](https://fccid.io/U9K).  From there, all it takes it sniffing the data and some decoding.  I used a Raspberry Pi and inexpensive 315MHz and 433MHz RF transceivers.  The [pigpio library](http://abyz.co.uk/rpi/pigpio/) was used for interfacing with the transceivers.  I wrote a crude Python module (RFUtils.py) that decodes/encodes waveforms to/from bytes. They key module in this repository, SimpliSafe.py, is what transforms the bytes to/from human-meaningful messages.
