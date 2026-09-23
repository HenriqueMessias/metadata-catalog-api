class DataCatalogError(Exception):
    """Base class for all domain-level errors raised by the service layer."""


class MetadataNotFoundError(DataCatalogError):
    def __init__(self, metadata_id: str):
        self.metadata_id = metadata_id
        super().__init__(f"Metadata '{metadata_id}' was not found")


class DuplicateMetadataError(DataCatalogError):
    def __init__(self, database_name: str, schema_name: str, table_name: str):
        self.database_name = database_name
        self.schema_name = schema_name
        self.table_name = table_name
        super().__init__(
            f"Table '{database_name}.{schema_name}.{table_name}' is already registered"
        )
