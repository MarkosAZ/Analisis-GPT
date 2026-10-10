# Estado de implementación

Esta matriz separa el contrato vigente de su implementación. Se actualiza después de verificar código y pruebas; no debe usarse la especificación como evidencia de que una integración ya funciona.

Clasificaciones: **IMPLEMENTADO Y CORRECTO**, **IMPLEMENTADO PARCIALMENTE**, **IMPLEMENTADO PERO INCORRECTO**, **NO IMPLEMENTADO**, **PLANIFICADO PARA UNA FASE POSTERIOR**. Una capacidad sin validación todavía no se declara correcta.

## Punto de partida y objetivo de la iteración

El checkout inicial solo contenía un README con título. La iteración 01 completó
Foundation. Tras la autorización para continuar y la petición de una extensión,
la iteración 02 desarrolla **Fase 2 — Calendario + providers + tracking** con
fuente manual. El cierre completo de Fase 2 sigue pendiente; no se declara un
scheduler remoto operativo ni una integración en producción.

## Matriz Foundation

Estado al cierre de Foundation. Se verificó con datos sintéticos y PostgreSQL 16 local; las integraciones de producción siguen en sus fases.

| Requisito | Estado | Evidencia |
| --- | --- | --- |
| Contexto consolidado, fases y ADRs | IMPLEMENTADO Y CORRECTO | Especificación completa de decisiones vigentes y pendientes |
| Paquete Python, configuración y dependencias | IMPLEMENTADO Y CORRECTO | Lockfile, instalación congelada, mypy estricto y build wheel/sdist |
| Nueve schemas y 47 tablas de dominio | IMPLEMENTADO Y CORRECTO | Cuatro migraciones, instalación desde cero y repetición sin cambios; tabla técnica adicional |
| Aislamiento privado y roles | IMPLEMENTADO Y CORRECTO | Consultas con identidad SQL efectiva, denegación de escalada y permisos futuros por defecto |
| Acceso temporal as_of y revisiones | IMPLEMENTADO Y CORRECTO | Rechazo de información futura y payloads mutables; guardas de procedencia SQL |
| Eventos/ciclos y aplazamientos | IMPLEMENTADO Y CORRECTO | No reparentar análisis ni evaluar contra resultados de otro ciclo |
| Idempotencia manual/programada | IMPLEMENTADO Y CORRECTO | Índices únicos independientes y claves deterministas |
| Locks TTL y fencing | IMPLEMENTADO Y CORRECTO | Expiración, propietario antiguo rechazado y adquisición concurrente real |
| Mapping ambiguo a revisión | IMPLEMENTADO Y CORRECTO | Decisión conservadora y una sola revisión SQL pendiente |
| Two/three-way, de-vig, edge y selector v1 | IMPLEMENTADO Y CORRECTO | Pruebas de dominio y constraints; vectores completos y matemática del método en SQL |
| Políticas paper/NO BET versionadas | IMPLEMENTADO Y CORRECTO | Borradores inactivos, activación prospectiva, una unidad y máximo edge positivo |
| Registry y holdout | IMPLEMENTADO Y CORRECTO | Versiones futuras rechazadas; RLS y ventanas solapadas; desbloqueo solo administrativo |
| Providers y almacenamiento local | IMPLEMENTADO Y CORRECTO | Protocolos, fixture RAW → NORMALIZED → as_of, hashes, inmutabilidad y seguridad de rutas |
| CI base | IMPLEMENTADO Y CORRECTO | actionlint y checks equivalentes locales; ejecución remota pendiente de subir cambios |
| Protección del HTML | IMPLEMENTADO Y CORRECTO | Copia intacta fuera del checkout, ignore, scanner y comprobación de wheel/sdist |

Estos estados corresponden a mecanismos Foundation. No equivalen a providers reales, estrategias validadas, feature store operativo o liquidación deportiva terminada. Para escribir resultados bajo un lock, el futuro repositorio de persistencia debe llamar a `ops.assert_event_lock` con el fencing token dentro de la misma transacción.

## Alcance posterior que no debe perderse

| Área | Estado | Fase/condición |
| --- | --- | --- |
| Fuente deportiva real, calendario, normalización y tracking | IMPLEMENTADO PARCIALMENTE | Provider manual, calendario/ciclos/CLI; falta aceptación con fuente real, temporadas y resolución de conflictos |
| Refresh/scheduler y lectura previa de tracking JSON | NO IMPLEMENTADO | Fase 2; falta fuente/recepción remota persistente; existe exportador local tracking_v1 |
| Betano/otras casas, snapshots RAW/Parquet y calidad de odds | IMPLEMENTADO PARCIALMENTE | Extensión captura RAW manual; normalización operativa, Parquet y calidad/frescura quedan para Fase 3 |
| Selector operativo y tasa NO_ELIGIBLE_LINE por segmento | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 3; preservar líneas excluidas |
| Estadísticas, noticias, lesiones, alineaciones y clima reales | PLANIFICADO PARA UNA FASE POSTERIOR | Integrar por dominio con disponibilidad temporal |
| Features deportivas y motor estadístico | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 4; fútbol → básquet → béisbol |
| Officialización, liquidación deportiva y reconciliación operativa | PLANIFICADO PARA UNA FASE POSTERIOR | Versionar reglas antes de operar; Foundation aporta estructura |
| Paper policies activas, thresholds NO BET y fuente de precio | PLANIFICADO PARA UNA FASE POSTERIOR | Resolver y congelar antes de Fase 5 prospectiva |
| Log-loss/calibración/CLV/ROI sobre historial real | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 5; métricas reproducibles y sin exclusión oportunista |
| Datasets Parquet, entrenamiento GBM y backtests walk-forward | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 6; manifests y validación temporal |
| Redes/embeddings/contexto/consenso | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 6; promoción solo tras mejora fuera de muestra |
| Workflow manual privilegiado de holdout | PLANIFICADO PARA UNA FASE POSTERIOR | Administración separada y auditoría |
| R2/Neon reales y backups privados | PLANIFICADO PARA UNA FASE POSTERIOR | Configuración, credenciales y pruebas de conectividad |
| JSON públicos optimizados y Pages | PLANIFICADO PARA UNA FASE POSTERIOR | Fase 7; schema_version, CSP y whitelist de exportación |
| Repositorio privado, tokens y apuestas reales | PLANIFICADO PARA UNA FASE POSTERIOR | Proyecto separado; nunca workflows públicos |
| Monitoreo de cron desactivado y recuperación tras huecos | PLANIFICADO PARA UNA FASE POSTERIOR | Antes del primer workflow programado operativo |

## Validación al cierre de la iteración 01 (histórica)

- `pytest`: **181 tests aprobados**, 149 unitarios y 32 de integración; sin skips en la ejecución completa.
- `ruff check`, `ruff format --check` y `mypy`: aprobados.
- Migraciones: cuatro aplicadas en PostgreSQL 16, instalación desde cero, repetición y detección de cambios de checksum comprobadas.
- `pip-audit`: ninguna vulnerabilidad conocida en las dependencias auditadas; el proyecto editable no se audita como dependencia externa.
- `actionlint 1.7.7`: workflow válido; binario oficial verificado por SHA-256.
- Build Python: wheel y sdist; inspección de contenido para excluir HTML, adjuntos y configuración local.
- Sin frontend: su build no aplica. No se ejecutó CI remoto ni se migró Neon.

El inventario, decisiones, correcciones y configuración posterior están en [ITERATION_01_REPORT.md](ITERATION_01_REPORT.md).

## Incremento de la iteración 02

| Capacidad | Estado | Evidencia/límite |
| --- | --- | --- |
| Panel, formulario, selector visible, revisión y descarga | IMPLEMENTADO Y CORRECTO | UI/DOM en Chromium y contrato JS→Python; APIs Chrome simuladas en pruebas |
| Instalación MV3, toolbar y sidePanel en navegador del usuario | IMPLEMENTADO PARCIALMENTE | Manifest y paquete listos; la política administrativa del cloud impide cargar extensiones |
| Entrada pública estricta y RAW inmutable | IMPLEMENTADO Y CORRECTO | Rechazo de campos extra/privados, hashes y referencias verificadas |
| Recepción confiable y disponibilidad de interpretación | IMPLEMENTADO Y CORRECTO | Reloj SQL, reproceso prospectivo y consulta histórica as_of |
| Importación y comandos idempotentes | IMPLEMENTADO Y CORRECTO | Reintentos, conflictos de UUID y dos importaciones concurrentes reales |
| Identidades de competición/equipos | IMPLEMENTADO Y CORRECTO | Confirmación explícita y revisión ante conflictos; sin fuzzy matching |
| Temporadas y reconciliación de eventos entre fuentes | NO IMPLEMENTADO | NULL explícito y cola de revisión; faltan contratos y resolución auditada |
| Aplazamientos/cancelación/abandono y ciclos | IMPLEMENTADO Y CORRECTO | Sucesor prepartido, terminales protegidos y tracking antiguo cerrado |
| Seguimiento local y tracking_v1 | IMPLEMENTADO Y CORRECTO | Activación/pausa por ciclo con request UUID y exportación de campos públicos |
| RAW de cuotas, incluidas enteras/asiáticas | IMPLEMENTADO Y CORRECTO | Conservación sin activar selección, modelos o paper |
| Review pública y separación SQL privada | IMPLEMENTADO Y CORRECTO | Cola ligada a observaciones, ledger inmutable y worker sin acceso privado |
| Fuente automática, R2/Neon y scheduler | NO IMPLEMENTADO | No hay credenciales ni recepción remota conectada; no se finge automatización de una pestaña local |

Las validaciones ejecutadas y el inventario de esta iteración se registran en
[ITERATION_02_REPORT.md](ITERATION_02_REPORT.md). La etiqueta «correcto» se limita
al alcance probado, no certifica autenticidad de datos manuales ni acceso real a
SofaScore/Betano.

## Siguiente incremento exacto

Completar **Calendario + providers + tracking**: aceptación de la extensión con
una página autorizada real, temporadas, resolución auditada de conflictos,
persistencia Neon/R2 y fuente/recepción ejecutable desde servidor. Después,
workflows operativos y recuperación de slots. No incorporar entrenamiento como
sustituto de estas tareas pendientes.

Criterios verificables para Fase 2:

1. Adapter autorizado desacoplado y fixtures de sus respuestas, con errores/reintentos sanitizados.
2. Persistir RAW antes de normalizar; conservar versión, hashes y disponibilidad de cada dato.
3. Resolver competición, temporada, equipos y evento mediante UUID y mappings; enviar ambigüedades a revisión.
4. Refrescar calendario idempotentemente, conservar ciclos ante aplazamientos y cubrir cancelación/abandono sin liquidar contra otro ciclo.
5. Seleccionar/desactivar seguimiento mediante entradas públicas no sensibles y producir `tracking.json` con contrato versionado.
6. Incorporar `refresh_calendar` y `tracking_scheduler` seguros, locks/TTL, observabilidad de slots y procedimiento de reactivación tras inactividad.
7. Probar el circuito con datos sintéticos y después una fuente autorizada; conservar el límite de Foundation sobre secretos y publicación.

El resto de los workflows se incorpora cuando exista su fase. No hay migraciones ejecutadas en producción, apuesta real, política paper activa, modelo entrenado, bucket R2 conectado ni sitio Pages desplegado por esta iteración.
