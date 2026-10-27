# Red de calles a partir del plano (prototipo)

Extrae el grafo de calles del plano de Construcciones (`web/plano.js`) para el futuro planificador de itinerarios.

1. `grafo.py`: rasteriza los lotes, las plazas y el arroyo, toma el espacio libre entre lotes y saca su esqueleto (el eje de cada pasillo).
2. `red.py`: arma el grafo, con un nodo por esquina o bifurcación y una arista por tramo, y clasifica cada tramo por su ancho.
   - Menos de 6,5 m: **peatonal**.
   - Entre 6,5 y 22 m: **calle**.
   - Junto al golf o al club: **borde, a confirmar**.
3. `ruta.py`: ancla cada U.F. a la calle más cercana y resuelve un ejemplo de ruta con Dijkstra y vecino más cercano + 2-opt, en dos modos:
   - **Vehículo**: calles y bordes.
   - **A pie**: suma los peatonales.

Requiere numpy, scipy, scikit-image, networkx y pillow. Se corre una sola vez: el resultado, después de revisarlo, se guarda como datos de la app.
