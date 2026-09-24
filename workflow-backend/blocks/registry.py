from blocks.base import BaseBlock

_registry: dict[str, type[BaseBlock]] = {}


def register_block(block_type: str):
    def decorator(cls: type[BaseBlock]) -> type[BaseBlock]:
        if block_type in _registry:
            raise ValueError(
                f"Block type '{block_type}' is already registered to "
                f"{_registry[block_type].__name__}, cannot also register {cls.__name__}."
            )
        _registry[block_type] = cls
        return cls

    return decorator


def get_block_class(block_type: str) -> type[BaseBlock]:
    if block_type not in _registry:
        raise KeyError(
            f"No block registered for type '{block_type}'. "
            f"Registered types: {sorted(_registry.keys())}"
        )
    return _registry[block_type]


def list_registered_types() -> list[str]:
    return list(_registry.keys())
