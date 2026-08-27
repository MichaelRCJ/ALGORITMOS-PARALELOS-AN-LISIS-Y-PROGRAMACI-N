import re


def limpiar_texto(valor):
    if valor is None:
        return ""
    texto = str(valor)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def apellido_autor(nombre):
    nombre = limpiar_texto(nombre)
    if not nombre:
        return ""
    partes = nombre.split()
    return partes[-1]


def generar_cita_apa(autores, anio):
    if not autores:
        return "(s. f.)"
    
    try:
        anio = int(anio)
    except:
        anio = "s. f."
    
    if len(autores) == 1:
        apellido = apellido_autor(autores[0])
        return f"({apellido}, {anio})"
    elif len(autores) == 2:
        apellido1 = apellido_autor(autores[0])
        apellido2 = apellido_autor(autores[1])
        return f"({apellido1} & {apellido2}, {anio})"
    else:
        apellido = apellido_autor(autores[0])
        return f"({apellido} et al., {anio})"


def generar_referencia_apa(fuente):
    autores = fuente.get("autores", [])
    if not isinstance(autores, list):
        autores = [str(autores)]
    
    autores_validos = [a for a in autores if limpiar_texto(a)]
    autores_apa = []
    
    for autor in autores_validos:
        partes = autor.split()
        if len(partes) >= 2:
            apellido = partes[-1]
            nombres = " ".join(partes[:-1])
            iniciales = ""
            for nombre in nombres.split():
                if nombre:
                    iniciales += nombre[0].upper() + ". "
            autores_apa.append(f"{apellido}, {iniciales.strip()}")
        else:
            autores_apa.append(autor)
    
    if not autores_apa:
        autores_texto = ""
    elif len(autores_apa) == 1:
        autores_texto = autores_apa[0]
    elif len(autores_apa) == 2:
        autores_texto = autores_apa[0] + " & " + autores_apa[1]
    else:
        autores_texto = ", ".join(autores_apa[:-1]) + ", & " + autores_apa[-1]
    
    anio = fuente.get("anio", "s. f.")
    titulo = limpiar_texto(fuente.get("titulo", ""))
    revista = limpiar_texto(fuente.get("revista", ""))
    doi = limpiar_texto(fuente.get("doi", ""))
    
    referencia = f"{autores_texto} ({anio}). {titulo}."
    
    if revista:
        referencia += f" {revista}."
    
    if doi:
        referencia += f" https://doi.org/{doi}"
    elif fuente.get("url"):
        referencia += f" {fuente.get('url')}"
    
    return referencia
