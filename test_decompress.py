import zlib
from sys import argv

input_zlib = argv[1]
output_txt = "archivo_descomprimido.txt"

with open(input_zlib, "rb") as f:
    compressed_data = f.read()


decompressed_data = zlib.decompress(compressed_data)

with open(output_txt, "wb") as f:
    f.write(decompressed_data)

print("¡Archivo descomprimido con éxito! Revisa:", output_txt)