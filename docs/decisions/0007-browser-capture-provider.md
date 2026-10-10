# ADR 0007 — Extensión como provider manual

Estado: aceptada para el incremento de Fase 2 solicitado tras Foundation.

El usuario pidió una extensión para consultar webs deportivas y casas de apuestas
y extraer cuotas. La fuente inicial pasa a ser una selección manual explícita,
sin presumir acceso a APIs ni permisos para scraping automatizado.

Se usa Manifest V3 con panel lateral y una pestaña normal. Un iframe impediría
consultar sitios que restringen framing. `activeTab` y `scripting` conceden acceso
temporal tras una acción del usuario; no se solicitan hosts permanentes, cookies,
historial ni credenciales. El dominio de deportes recibe un contrato versionado,
independiente del DOM o del nombre del sitio.

La exportación es JSON de campos permitidos y una sola observación revisada. Se
conserva origen, sin rutas o queries que puedan contener tokens. No se captura el
HTML entero, una boleta ni tráfico de red. La revisión humana es necesaria; los
filtros de DOM no prueban privacidad ni autenticidad de una página arbitraria.

El backend valida, registra una recepción confiable en PostgreSQL, persiste RAW,
normaliza y registra una observación con disponibilidad propia. El reloj del
navegador no puede retroceder `available_at`. Los reintentos preservan recibo y
hash; la normalización/revisión posterior no reescribe observaciones anteriores.

Las identidades se confirman explícitamente. Temporada no suministrada queda NULL.
Los cambios de fecha prepartido crean un ciclo sucesor y exigen selección nueva
de tracking. Conflictos con eventos iniciados/terminales pasan a revisión, sin
alterar predicciones de otro ciclo. Las transacciones cortas usan advisory lock;
los futuros análisis conservan su contrato independiente de TTL y fencing.

Se admite capturar cuotas RAW ahora por petición expresa, manteniendo su uso
operativo para Fase 3. No cambia `line_selector_v1`, no se activan políticas paper
y no se introducen apuestas reales. La extensión es una herramienta de entrada;
no adelanta la aplicación pública de Pages ni agrega PostgreSQL al navegador.

Una extensión manual no es una fuente cron ejecutable en Actions. Se posponen
workflows remotos hasta contar con recepción autenticada/persistencia y una
fuente realmente ejecutable; no se crean jobs de apariencia operativa sin esos
requisitos. Esto preserva el plan por fases y deja Fase 2 parcialmente completada.
