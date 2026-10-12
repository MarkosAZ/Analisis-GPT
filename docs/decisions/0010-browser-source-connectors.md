# ADR 0010 — Conectores incluidos en el navegador

Estado: implementada; aceptación con sitios reales pendiente.

El usuario pidió reproducir el funcionamiento de la [extensión Analisis-BDP,
commit 7b0dcd97](https://github.com/LuisP11127/Analisis-BDP/tree/7b0dcd97b4db471057508ba47df04b0bb0d4ccaa/extension).
Se inspeccionaron su manifest, puente, controlador, red, diagnóstico y conectores.
La referencia aporta endpoints y formatos que permiten desarrollar sin esperar
a que el cloud pueda abrir las cinco webs. El producto se ejecuta en el navegador.

Se implementan conectores propios y fijos para SofaScore, Betano, Apuesta Total
y Flashscore. La configuración por casillas concede permisos por host; la web
inicia/cancela la cola, muestra datos y descarga capturas/diagnóstico. Te Apuesto
no aparece en esa referencia y conserva estado pendiente. No se incorporan sus
fuentes extra, modelos o escrituras a GitHub: no corresponden a esta fase.

La referencia captura tráfico/encabezados, transfiere estado completo, prueba
rutas alternativas y ofrece tokens de escritura en GitHub. Copiar esos mecanismos
entraría en conflicto con la frontera privada y la trazabilidad de este proyecto.
Se sustituye por GETs públicos acotados y proyección de campos públicos dentro de
Betano, sin hooks, clics, encabezados de cuenta ni errores que incluyan respuestas.
Apuesta Total puede usar la sesión normal del navegador para el sportsbook;
no se lee ni exporta su cookie y no se fuerza login/logout. Una denegación termina
esa fuente, sin rutas alternativas. Se solicitan solo ML0/OU0 para diez eventos,
no se enumeran cientos de tipos de mercado como hacía la referencia.

Los conectores emiten `browser_capture_v3` / `AUTOMATIC_SOURCE`, con normalizador
v3 y calidad SOURCE_UNVERIFIED; v1/v2 se conservan sin modificar sus manifests.
Calendario exige IDs estables y semántica de estados; FINISHED sin inicio real no
se inventa. Cuotas exige mercados completos, mismo evento/periodo/línea; formatos
no reconocidos se cuentan como omitidos. Se conservan enteras y asiáticas como RAW,
sin cambiar `line_selector_v1`. Ninguna vista previa crea eventos SQL o predicciones.

No hay migraciones ni dependencias nuevas. Persistencia y PIT conservan recibo
SQL, objetos inmutables e importación idempotente. Tests de contrato y Chromium
con fixtures prueban el código; no demuestran que un proveedor concreto responda
desde cualquier país ni que sus formatos no hayan cambiado. El diagnóstico local
identifica denegaciones y cambios sin falsos resultados. La aceptación real del
ZIP y el soporte de más deportes/mercados son siguientes incrementos.
