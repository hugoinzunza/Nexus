"""Núcleo (hub) de Nexus.

Este paquete contiene el corazón del sistema: el servidor HTTP, el cargador
de módulos y el contrato base que todo módulo debe cumplir. La idea es que el
núcleo sea pequeño y estable, y que toda la funcionalidad nueva (trading,
música, y lo que venga) viva en módulos enchufables dentro de `modules/`.
"""
