# ADR 0006 — Contratos persistidos y límites de Foundation

Estado: aceptada para Foundation.

La lista explícita del historial contiene **47** tablas de dominio. La cifra 45
usada durante el inventario inicial era un error de recuento; no se eliminan
tablas para ajustarla. `ops.schema_migrations` es una tabla técnica adicional.

Se utiliza Python 3.12, PostgreSQL 16 y migraciones SQL con checksum y advisory
lock. Una nueva migración conserva el historial de las anteriores. La instalación
completa se valida en una base desechable independiente.

Los vectores de probabilidades deben completarse en una misma transacción. Los
constraint triggers diferidos rechazan vectores parciales o desnormalizados al
commit. Precios, probabilidades, inputs y vínculos de predicción quedan inmutables.
Los modelos de producción solo se atribuyen a decisiones dentro de su deployment.

El ledger de paper contiene únicamente predicciones oficiales LIVE. Se puede
materializar tras officialización usando el precio, la política y el instante
simulado de la decisión original. `placed_at` significa ese instante simulado,
no una apuesta real ni el timestamp de inserción. Fase 5 definirá cómo conservar
los candidatos provisionales prepartido y las reglas exactas de officialización;
Foundation no inventa esas reglas. La fuente de precio y los thresholds siguen
sin activar.

El holdout se protege en contratos Python y mediante RLS/privilegios SQL. Una
ventana de desarrollo que solape un holdout tampoco es evaluable. Los permisos de
RAW/datasets/modelos en object storage real se diseñarán al incorporar R2; el
backend local no implementa identidades IAM ni promete protección frente al
propietario del filesystem.

Los locks tienen tokens monotónicos y recuperación tras TTL. El writer deberá
comprobar el token en la transacción que persiste resultados. Foundation ofrece y
prueba esa operación; el worker deportivo todavía no existe.

El matcher de Foundation usa `mapping_policy_v1` con confianza mínima 0.99 y exige
una única identidad que la supere. Es una decisión técnica conservadora para los
fixtures, no un umbral calibrado sobre proveedores reales. Su sustitución exige
una nueva versión y validación al integrar la primera fuente autorizada.

La elegibilidad v1 mantiene enteras/asiáticas fuera. La prioridad entre varias
half-lines se proporciona explícitamente; no se inventa una estrategia de línea
principal. El desempate es determinista. No hay política de apuesta en producción.
