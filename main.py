from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

# Inicializar la aplicación
app = FastAPI(
    title="Mi API REST de Ejemplo",
    description="Una API básica con operaciones CRUD utilizando FastAPI",
    version="1.0.0"
)

# 1. Definir el esquema de datos usando Pydantic (esto valida automáticamente las entradas y salidas)
class Item(BaseModel):
    id: Optional[int] = None
    nombre: str
    descripcion: Optional[str] = None
    precio: float
    en_stock: bool = True

# Base de datos simulada en memoria (para evitar configurar una base de datos real por ahora)
db_items = [
    Item(id=1, nombre="Laptop Pro", descripcion="Laptop de alta gama con 16GB RAM", precio=1250.00, en_stock=True),
    Item(id=2, nombre="Mouse Inalámbrico", descripcion="Mouse ergonómico Bluetooth", precio=29.99, en_stock=True)
]

# --- RUTAS / ENDPOINTS ---

@app.get("/", tags=["General"])
def leer_raiz():
    """Endpoint raíz que da la bienvenida a la API."""
    return {"mensaje": "¡Bienvenido a la API REST con FastAPI!", "docs": "/docs"}

@app.get("/items", response_model=List[Item], tags=["Items"])
def obtener_items(en_stock: Optional[bool] = None):
    """Obtener la lista completa de items, con opción de filtrar por stock."""
    if en_stock is not None:
        return [item for item in db_items if item.en_stock == en_stock]
    return db_items

@app.get("/items/{item_id}", response_model=Item, tags=["Items"])
def obtener_item_por_id(item_id: int):
    """Obtener un item específico buscando por su ID."""
    for item in db_items:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=404, detail="El item solicitado no existe")

@app.post("/items", response_model=Item, status_code=201, tags=["Items"])
def crear_item(item: Item):
    """Crear un nuevo item en la base de datos simulada."""
    # Asignar un ID automático incremental
    nuevo_id = max([i.id for i in db_items], default=0) + 1
    item.id = nuevo_id
    db_items.append(item)
    return item

@app.put("/items/{item_id}", response_model=Item, tags=["Items"])
def actualizar_item(item_id: int, item_actualizado: Item):
    """Actualizar por completo un item existente."""
    for index, item in enumerate(db_items):
        if item.id == item_id:
            item_actualizado.id = item_id  # Mantener el ID original
            db_items[index] = item_actualizado
            return item_actualizado
    raise HTTPException(status_code=404, detail="No se pudo actualizar, el item no existe")

@app.delete("/items/{item_id}", tags=["Items"])
def eliminar_item(item_id: int):
    """Eliminar un item por su ID."""
    for index, item in enumerate(db_items):
        if item.id == item_id:
            db_items.pop(index)
            return {"mensaje": f"Item con ID {item_id} eliminado exitosamente"}
    raise HTTPException(status_code=404, detail="No se pudo eliminar, el item no existe")