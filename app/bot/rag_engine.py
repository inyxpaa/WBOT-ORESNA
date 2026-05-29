"""
app/bot/rag_engine.py - Motor de Búsqueda Inteligente (RAG)
Generación Aumentada por Recuperación sobre el catálogo de propiedades.

Estrategia híbrida:
  1. Filtrado estructurado por tipo, precio y habitaciones
  2. Búsqueda semántica TF-IDF por zona/descripción
  3. Devuelve top-3 propiedades más relevantes
"""
import re
import logging

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class MotorRAG:
    """
    Motor de recuperación de propiedades del catálogo CSV.
    Se inicializa una vez al arrancar y mantiene los datos en memoria.
    """

    def __init__(self):
        self.df: pd.DataFrame | None = None
        self.vectorizer: TfidfVectorizer | None = None
        self.matrix = None

    def cargar_propiedades(self, ruta: str = "data/propiedades.csv") -> None:
        """
        Carga el catálogo CSV y construye el índice TF-IDF para búsqueda semántica.
        Columnas requeridas: id, titulo, tipo, zona, precio, habitaciones,
                             banos, metros, descripcion, estado
        """
        try:
            self.df = pd.read_csv(ruta)

            # Crear texto enriquecido por propiedad para indexado semántico
            self.df["_texto"] = self.df.apply(
                lambda r: (
                    f"{r['titulo']} {r['tipo']} {r['zona']} "
                    f"{r['descripcion']} "
                    f"{r['habitaciones']} habitaciones "
                    f"{r['metros']} metros cuadrados"
                ),
                axis=1,
            )

            # Vectorización TF-IDF (no requiere descargar ningún modelo)
            self.vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                max_features=8000,
                sublinear_tf=True,
            )
            self.matrix = self.vectorizer.fit_transform(self.df["_texto"])

            logger.info(f"{len(self.df)} propiedades indexadas en el motor RAG")

        except FileNotFoundError:
            logger.error(f"No se encontro el catalogo en '{ruta}'")
            self.df = pd.DataFrame()
        except Exception as e:
            logger.error(f"Error cargando propiedades: {e}")
            self.df = pd.DataFrame()

    def buscar(
        self,
        tipo: str | None = None,
        zona: str | None = None,
        presupuesto_max: int | None = None,
        habitaciones: int | None = None,
    ) -> list[dict]:
        """
        Busca propiedades aplicando filtros estructurados y búsqueda semántica.

        Args:
            tipo: 'venta', 'alquiler' o 'venta_propia'
            zona: Texto libre (barrio, ciudad, zona)
            presupuesto_max: Precio máximo en euros
            habitaciones: Número de habitaciones deseadas

        Returns:
            Lista de hasta 3 propiedades como diccionarios
        """
        if self.df is None or len(self.df) == 0:
            logger.warning("Catalogo vacio o no cargado")
            return []

        df = self.df.copy()

        # 1. Filtrar solo propiedades disponibles
        if "estado" in df.columns:
            df = df[df["estado"].str.lower() == "disponible"]

        # 2. Filtrar por tipo de operación
        if tipo and tipo != "venta_propia":
            mask = df["tipo"].str.lower().str.contains(tipo.lower(), na=False)
            if mask.any():
                df = df[mask]

        # 3. Filtrar por presupuesto (con tolerancia del 15%)
        if presupuesto_max:
            try:
                limite = float(presupuesto_max) * 1.15
                price_mask = df["precio"] <= limite
                if price_mask.any():
                    df = df[price_mask]
            except (ValueError, TypeError):
                pass

        # 4. Filtrar por número de habitaciones (con flexibilidad ±1)
        if habitaciones:
            try:
                h = int(habitaciones)
                hab_mask = df["habitaciones"].between(max(0, h - 1), h + 1)
                exact_mask = df["habitaciones"] == h
                if exact_mask.any():
                    df = df[exact_mask]
                elif hab_mask.any():
                    df = df[hab_mask]
            except (ValueError, TypeError):
                pass

        if len(df) == 0:
            logger.info("No se encontraron propiedades con esos filtros exactos")
            return []

        # 5. Búsqueda semántica por zona si hay vectorizador
        if zona and self.vectorizer is not None:
            try:
                indices = df.index.tolist()
                sub_matrix = self.matrix[indices]
                query_vec = self.vectorizer.transform([zona])
                scores = cosine_similarity(query_vec, sub_matrix).flatten()

                n = min(3, len(df))
                top_idx = scores.argsort()[-n:][::-1]
                resultado = df.iloc[top_idx]
            except Exception as e:
                logger.error(f"Error en búsqueda semántica: {e}")
                resultado = df.head(3)
        else:
            resultado = df.head(3)

        propiedades = resultado.drop(columns=["_texto"], errors="ignore").to_dict(
            "records"
        )
        logger.info(f"RAG encontro {len(propiedades)} propiedades")
        return propiedades

    def total(self) -> int:
        """Devuelve el total de propiedades en catálogo"""
        return len(self.df) if self.df is not None else 0


# Instancia global (singleton)
motor_rag = MotorRAG()
