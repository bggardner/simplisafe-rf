#!/usr/bin/python3
import cymysql
from select import select
from simplisafe.pigpio import Transceiver

RX_315MHZ_GPIO = 27 # Connected to DATA pin of 315MHz receiver
RX_433MHZ_GPIO = 17 # Connected to DATA pin of 433MHz receiver

cnx = cymysql.connect(user='pi', passwd='raspberry', unix_socket='/var/run/mysqld/mysqld.sock', port=3306, db='mydb')
cursor = cnx.cursor()

with Transceiver(rx=RX_315MHZ_GPIO) as txr315, Transceiver(rx=RX_433MHZ_GPIO) as txr433:
    while True:
        rlist, _, _ = select([txr315, txr433], [], [])
        for txr in rlist:
            try:
                msg = txr.recv() # simplisafe.message.Message object
            except Exception as e:
                print(str(e))
                continue
            msg_str = "".join(map("{:02X}".format, bytes(msg))) # Convert to hex string for storage
            print(str(msg.__class__.__name__) + ": " + msg_str)
            cursor.execute("INSERT INTO `log` (`msg`) VALUES (%s)", (msg_str,)) # Use simplisafe.messages.Message.factory() to restore object
            cnx.commit()

cursor.close()
cnx.close()
