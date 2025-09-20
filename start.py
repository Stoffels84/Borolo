from phue import Bridge

BRIDGE_IP = "192.168.0.147"  # vervang dit door jouw bridge IP

b = Bridge(BRIDGE_IP)

# Eerste keer moet je de fysieke knop op de Hue Bridge indrukken!
b.connect()

# Lijst van lampen
lights = b.get_light_objects("name")
print("Beschikbare lampen:")
for name in lights:
    print("-", name)

# Zet eerste lamp aan
first = list(lights.keys())[0]
print(f"Zet {first} aan...")
b.set_light(first, 'on', True)
