# Corrección temporal

Una predicción histórica solo puede usar información disponible cuando se tomó la decisión. Este contrato afecta a estadísticas, odds, noticias, lesiones, alineaciones, clima, features, datasets, backtests y selección de modelos/políticas.

## Relojes distintos

| Campo | Significado |
| --- | --- |
| `occurred_at` | Cuándo ocurrió el hecho o a qué instante se refiere |
| `available_at` | Primer instante en que esa versión del dato estuvo disponible para el pipeline |
| `available_at_source` | OBSERVED o ESTIMATED; MIXED solo para conjuntos agregados |
| `fetched_at` | Cuándo se capturó la respuesta concreta |
| `decision_time` | Corte temporal de la decisión que se reconstruye |

Todos usan timestamps con zona horaria y se normalizan a UTC. No se aceptan fechas ambiguas sin zona. La condición de inclusión es `available_at <= decision_time`.

Ejemplo: una lesión ocurrió a las 10:00, se publicó a las 12:15 y se observa a las 12:20. Un análisis de las 11:00 no puede utilizarla. Si solo se conoce el timestamp de captura, no se inventa una disponibilidad anterior como OBSERVED. Una estimación histórica se etiqueta ESTIMATED y aparece en el reporte de calidad.

Una previsión meteorológica para las 20:00 puede haberse publicado a las 08:00; es elegible para una decisión de las 12:00 si se conserva esa versión. Filtrar ciegamente `occurred_at <= decision_time` eliminaría información legítima y no reemplaza el control de disponibilidad.

## Acceso y trazabilidad

El acceso a datos para features pasa por `as_of(decision_time)`. Una operación estricta debe rechazar inputs futuros suministrados a una feature; una consulta temporal devuelve únicamente las versiones elegibles. Las revisiones posteriores no sustituyen retrospectivamente el estado anterior.

El manifiesto registra inputs, URI/hash, timestamps/calidad temporal y versiones de provider, adapter, normalizador, schema, feature pipeline, código, modelos y políticas. Los objetos RAW son inmutables. El sistema debe poder explicar por qué un dato fue elegible, no solo cuándo ocurrió el evento descrito.

La Foundation prueba el contrato y la persistencia básica. La implementación de cada fuente y de cada feature deportiva deberá integrarse con él en fases posteriores; tener un helper `as_of` no demuestra por sí solo ausencia de leakage en código futuro.

## Ciclos y resultados

El corte temporal también necesita identidad correcta. Un análisis del ciclo aplazado A no se evalúa con el resultado del ciclo B reprogramado. Los resultados publicados después de la decisión pueden usarse como etiquetas para evaluar una predicción ya fijada; nunca entran como features de esa misma decisión.

La officialización y el cálculo de métricas deben utilizar el inicio real y una regla versionada. No eliminar predicciones oficiales stale para mejorar retrospectivamente el track record. Las reglas deportivas de abandono/cancelación requieren evidencia y, cuando falte, revisión.

## Modelos, políticas y experimentos

El modelo usado por una decisión debe ser una versión desplegada para ese instante, con artefacto trazable y entrenamiento temporalmente válido. Una versión promovida hoy no adquiere track record live de decisiones pasadas. Lo mismo aplica a selección de mercados, calibración, umbrales NO BET y paper policies.

Los backtests usan ventanas cronológicas y walk-forward; reportan OBSERVED frente a ESTIMATED. El holdout final está bloqueado para evaluación habitual y no puede utilizarse para ajustar hiperparámetros o reglas. Un desbloqueo explícito queda auditado y termina la condición de holdout intacto de esa ventana.

## Casos protegidos por pruebas

- Datos disponibles después del corte se excluyen o rechazan, aunque el hecho sea anterior.
- El instante exacto del corte es elegible; los timestamps sin zona se rechazan.
- Reprogramar no mueve análisis ni permite una evaluación entre ciclos.
- Una versión de modelo/política futura no se aplica a una decisión anterior.
- Un holdout bloqueado no está disponible para el acceso normal de evaluación.
- Los objetos usados por una decisión no cambian de contenido silenciosamente.

Cada futura feature y adapter deberá aportar pruebas de sus propios timestamps, correcciones y joins; la cobertura de Foundation no sustituye esa validación.

## Capturas de navegador

`captured_at` es una declaración manual. La base fija la recepción confiable y
rechaza timestamps de navegador futuros. RAW normalizado usa esa recepción como
disponibilidad OBSERVED; una interpretación con mapping/ciclo exige además el
`available_at` de `browser_observations`. Reprocesar tras confirmar una identidad
crea una observación nueva, sin backdating. El estado actual de `event_cycles` y
`tracking.json` no sustituye esa historia para datasets/backtests.

`observations_as_of` devuelve las observaciones conocidas a la fecha solicitada,
con referencia al manifest inmutable. La futura feature debe seleccionar sus
revisiones y consultar resultados/mappings temporalmente; este incremento no
implementa entrenamiento ni un feature builder deportivo.
