import pigpio
import SimpliSafe
from time import sleep

done = False
skip = False
encoded = ''
t = None
start_flag0 = False
start_flag1 = False
sync_buffer = ''
pi = None

def _recv_cbf(gpio, level, tick):
    global pi, done, skip, encoded, t, sync_buffer, start_flag0, start_flag1
    if t is None:
        t = tick
        return
    if skip:
        skip = False # Previous transition was a glitch
        return
    if t > tick:
      dt = ((tick << 32) - t) / 1000 # Tick overflow
    else:
      dt = (tick - t) / 1000 # Convert to ms
    if dt < 0.4:
        skip = True # Glitch
        #print("Glitch detected")
        return
    if dt > 2.1:
        if start_flag1:
            pi.set_glitch_filter(gpio, 0)
            pi.stop()
            done = True # End of transmission
            #print("End of transmission")
        else:
            t = tick
            start_flag0 = False
            #print("Long pulse detected")
        return
    t = tick
    if dt > 1.9:
        if sync_buffer == '1111':
            if level == 1:
                start_flag0 = True
                start_flag1 = False
            elif start_flag0:
                start_flag1 = True
                encoded = ''
            #print("Start sequence detected")
        else:
            start_flag0 = False
        return
    if dt > 1.1:
        encoded += 'X' # Invalid duration
    elif dt >= 0.9:
        encoded += '1'
    elif dt > 0.6:
        encoded += 'X' # Invalid duration
    else:
        encoded += '0'
    sync_buffer += encoded
    sync_buffer = sync_buffer[-4:]
    if not start_flag1:
        encoded = ''

def recv(gpio: int):
    global pi, done, skip, encoded, t, start_flag0, start_flag1, sync_buffer
    while True:
        done = False
        skip = False
        encoded = ''
        t = None
        start_flag0 = False
        start_flag1 = False
        sync_buffer = ''

        pi = pigpio.pi()
        pi.set_mode(gpio, pigpio.INPUT)
        pi.set_glitch_filter(gpio, 50)
        #pi.set_noise_filter(gpio, 400, 400)
        pi.callback(gpio, pigpio.EITHER_EDGE, _recv_cbf)

        while not done:
            pass

        print('')
        #print('Message received @ ' + str(datetime.now()))
        #print('Message received: ' + encoded)
        if len(encoded) <= 4:
            print('Message ignored (not enough bytes)')
            continue
        if encoded.find('X') != -1:
            print('Message ignored (bad pulse width)')
            continue

        decoded = ''
        for i in range(0, len(encoded), 4):
            nibble = "{:X}".format(int(encoded[i:i+4][::-1], 2))
            decoded += nibble
        print('Decoded: ' + decoded)

        origin = int(decoded[16:18][::-1], 16)
        if origin == SimpliSafe.Message.OriginType.BASE_STATION:
            unswapped = decoded[:-2]
        else:
            rd = decoded.find('F' + decoded[0:4])
            unswapped = decoded[:rd]

        if len(unswapped) % 2 == 1:
            print('Message ignored (odd byte count: ' + str(len(unswapped)) + ')')
            continue
        swapped = bytes()
        for i in range(0, len(unswapped), 2):
            swapped += bytes([int(unswapped[i + 1] + unswapped[i], 16)])

        s = ''
        for i in range(0, len(swapped)):
            s += "{:02X}".format(swapped[i])
        print("Swapped: " + s)
        return SimpliSafe.Message.factory(swapped)

def send(gpio: int, msg: SimpliSafe.Message, mode='script'):
    if isinstance(msg, SimpliSafe.SensorMessage):
        for i in range(3):
            if mode == 'wave':
                send_wave(gpio, msg)
            elif mode == 'script':
                send_script(gpio, msg)
            else:
                 raise ValueError
            sleep(2)
    else:
        if mode == 'wave':
            send_wave(gpio, msg)
        elif mode == 'script':
            send_script(gpio, msg)
        else:
            raise ValueError
    print("Message sent successfully.")

def send_wave(gpio: int, msg: SimpliSafe.Message):
    w = []
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        syncs = 150
    elif isinstance(msg, SimpliSafe.KeypadMessage):
        syncs = 40
    elif isinstance(msg, SimpliSafe.SensorMessage):
        syncs = 20
    else:
        raise TypeError
    next_bit = 0
    for i in range(syncs):
        w.append(pigpio.pulse(0, gpio, 1000))
        w.append(pigpio.pulse(gpio, 0, 1000))
    wd = []
    wd.append(pigpio.pulse(0, gpio, 2000))
    wd.append(pigpio.pulse(gpio, 0, 2000))
    next_bit = 0
    for msg_byte in bytes(msg):
        for i in range(8):
            if msg_byte & (1 << i):
                d = 1000
            else:
                d = 500
            if next_bit == 1:
                wd.append(pigpio.pulse(gpio, 0, d))
            else:
                wd.append(pigpio.pulse(0, gpio, d))
            next_bit ^= 1    
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        ds = [1000, 1000, 500, 500]
        for d in ds:
            if next_bit == 1:
                wd.append(pigpio.pulse(gpio, 0, d))
            else:
                wd.append(pigpio.pulse(0, gpio, d))
            next_bit ^= 1
    for i in range(4):
        if next_bit == 1:
            wd.append(pigpio.pulse(gpio, 0, 1000))
        else:
            wd.append(pigpio.pulse(0, gpio, 1000))
        next_bit ^= next_bit
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        ws = []
        for i in range(18):
            ws.append(pigpio.pulse(0, gpio, 1000))
            ws.append(pigpio.pulse(gpio, 0, 1000))
        w = w + wd + ws + wd + ws + wd
    elif isinstance(msg, SimpliSafe.ComponentMessage):
        w = w + wd + wd
    else:
        raise TypeError
    pi = pigpio.pi()
    pi.wave_clear()
    pi.wave_add_generic(w)
    print("Micros: " + str(pi.wave_get_micros()) + "/" + str(pi.wave_get_max_micros()))
    print("Pulses: " + str(pi.wave_get_pulses()) + "/" + str(pi.wave_get_max_pulses()))
    print("CBs: " + str(pi.wave_get_cbs()) + "/" + str(pi.wave_get_max_cbs()))
    wid = pi.wave_create()
    if wid < 0:
        raise Exception("Message wave creation failed!")
    pi.wave_send_once(wid)
    while pi.wave_tx_busy():
        sleep(1)
    pi.wave_clear()
    pi.stop()

def send_script(gpio: int, msg: SimpliSafe.Message):
    s= []
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        s.append("ld v0 150 tag 0 w " + str(gpio) + " 0 mics 1000 w " + str(gpio) + " 1 mics 1000 dcr v0 jp 0")
    elif isinstance(msg, SimpliSafe.KeypadMessage):
        s.append("ld v0 40 tag 0 w " + str(gpio) + " 0 mics 1000 w " + str(gpio) + " 1 mics 1000 dcr v0 jp 0")
    elif isinstance(msg, SimpliSafe.SensorMessage):
        s.append("ld v0 20 tag 0 w " + str(gpio) + " 0 mics 1000 w " + str(gpio) + " 1 mics 1000 dcr v0 jp 0")
    else:
        raise TypeError
    preamble = "w " + str(gpio) + " 0 mics 2000 w " + str(gpio) + " 1 mics 2000"
    s.append(preamble)
    next_bit = 0
    for msg_byte in bytes(msg):
        for i in range(8):
            s_i = "w " + str(gpio) + " " + str(next_bit) + " mics "
            if msg_byte & (1 << i):
                s_i += "1000"
            else:
                s_i += "500"
            s.append(s_i)
            next_bit ^= 1
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        s.append("w " + str(gpio) + " " + str(next_bit) + " mics 1000")
        s.append("w " + str(gpio) + " " + str(next_bit) + " mics 1000")
        s.append("w " + str(gpio) + " " + str(next_bit) + " mics 500")
        s.append("w " + str(gpio) + " " + str(next_bit) + " mics 500")
        next_bit ^= 1
    for i in range(4):
        s.append("w " + str(gpio) + " " + str(next_bit) + " mics 1000")
        next_bit ^= 1
    sd = s[1:]
    if isinstance(msg, SimpliSafe.BaseStationKeypadMessage):
        s.append("ld v0 18 tag 1 w " + str(gpio) + " " + str(next_bit) + " mics 1000 w " + str(gpio) + " " + str(next_bit) + " mics 1000 dcr v0 jp 1")
        next_bit ^= 1
        s = s + sd
        s.append("ld v0 18 tag 2 w " + str(gpio) + " " + str(next_bit) + " mics 1000 w " + str(gpio) + " " + str(next_bit) + " mics 1000 dcr v0 jp 2")
        next_bit ^= 1
        s = s + sd
    elif isinstance(msg, SimpliSafe.ComponentMessage):
        s = s + sd
    else:
        raise TypeError
    s.append("w " + str(gpio) + " 0")
    pi = pigpio.pi()
    pi.set_mode(gpio, pigpio.OUTPUT)
    sid = pi.store_script(bytes(" ".join(s), 'ascii'))
    if sid < 0:
        raise Exception("Script failed to store!")
    pi.run_script(sid)
    while True:
        (s, _) = pi.script_status(sid)
        if s == pigpio.PI_SCRIPT_FAILED:
            raise Exception("Message send script failed!")
        elif s == pigpio.PI_SCRIPT_HALTED:
            pi.delete_script(sid)
            break
    pi.stop()
