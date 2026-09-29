from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL


print(
    f"Loading embedding model: "
    f"{EMBEDDING_MODEL}"
)


model = SentenceTransformer(
    EMBEDDING_MODEL
)


def generate_embedding(
    text: str
) -> list[float]:

    if not text or not text.strip():

        raise ValueError(
            "Text cannot be empty."
        )

    embedding = model.encode(
        text,
        normalize_embeddings=True
    )

    return embedding.tolist()