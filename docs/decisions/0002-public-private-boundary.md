# ADR 0002 — Apuestas reales fuera del repositorio público

Estado: aceptada.

## Contexto

Los inputs, logs y artifacts de Actions públicos pueden ser visibles. Registrar una apuesta mediante un workflow público filtra información aunque PostgreSQL y la exportación posterior sean privados.

## Decisión

El futuro repositorio privado ejecuta el registro/exportación de apuestas con sus propios secretos. PostgreSQL separa `private_betting` y deniega USAGE al worker público y al de entrenamiento. Las revisiones privadas también permanecen separadas. El repositorio público puede contener la definición del schema y pruebas sintéticas, nunca apuestas reales.

Se emplearán dos tokens con repositorios acotados: uno público con Actions write, otro privado con Actions write y Contents read. El frontend privado se construirá en una fase posterior.

## Consecuencias

No se aceptan datos reales como inputs de workflows públicos. Los permisos de runtime son distintos de los de migración. La configuración privada y sus credenciales no son necesarias para verificar Foundation.
