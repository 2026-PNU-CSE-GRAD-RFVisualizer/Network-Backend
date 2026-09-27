
import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[sniffer] connected rc={reason_code} -> subscribe '#'")
    client.subscribe("#")

def on_message(client, userdata, msg):
    print(f"[recv] topic={msg.topic}  payload={msg.payload[:150]!r}")

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sniffer")
c.on_connect = on_connect
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
print("listening on 127.0.0.1:1883 ... (Ctrl+C to stop)")
c.loop_forever()
