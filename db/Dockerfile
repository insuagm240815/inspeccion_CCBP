# Base de datos para Railway: MariaDB con el esquema y los datos base incluidos.
# Railway no permite montar ./db/init como en docker compose, así que se copian dentro de la imagen.
FROM mariadb:11.4.4
COPY init/ /docker-entrypoint-initdb.d/
# Los datos van en una subcarpeta del volumen (/var/lib/mysql): así no molesta un "lost+found" en la raíz.
CMD ["mariadbd", "--datadir=/var/lib/mysql/datos"]
