import logging
import posixpath
from typing import Dict, List, Optional, Set

from ...models.schemas import (
    ArchitecturalComponent,
    EntryPointCandidate,
    ParsedFile,
    RepoAnalysisResult,
)

logger = logging.getLogger(__name__)


class ComponentClassifier:
    """
    Classifies repository source and configuration files into standard architectural layers
    with confidence scores and concrete evidence. Unknown files remain explicitly categorized as 'unknown'.
    """

    def classify_components(
        self,
        parsed_files: List[ParsedFile],
        entry_points: List[EntryPointCandidate],
        analysis: Optional[RepoAnalysisResult] = None,
    ) -> List[ArchitecturalComponent]:
        classified: List[ArchitecturalComponent] = []

        # High-confidence entry point file paths
        high_conf_entry_files: Set[str] = {
            ep.file_path for ep in entry_points if ep.confidence == "high"
        }
        all_entry_files: Set[str] = {ep.file_path for ep in entry_points}

        for pf in parsed_files:
            file_p = pf.file_path
            path_lower = file_p.lower()
            base_name = posixpath.basename(file_p).lower()
            dir_parts = [p.lower() for p in posixpath.dirname(file_p).split("/") if p]

            category = "unknown"
            confidence = "low"
            evidence: List[str] = []

            # 1. Tests
            if (
                any(p in ("test", "tests", "__tests__", "spec", "specs") for p in dir_parts)
                or base_name.startswith("test_")
                or base_name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
            ):
                category = "test"
                confidence = "high"
                evidence.append("File located in test directory or matches test naming pattern")

            # 2. Configuration files
            elif (
                any(p in ("config", "configs", "configuration", "settings") for p in dir_parts)
                or base_name in (
                    "package.json", "tsconfig.json", "vite.config.ts", "vite.config.js",
                    "webpack.config.js", "dockerfile", "docker-compose.yml", "setup.py",
                    "pyproject.toml", "cargo.toml", "go.mod", "pom.xml", "makefile",
                    "settings.py", "config.py",
                )
            ):
                category = "configuration"
                confidence = "high"
                evidence.append("File contains application or build configuration")

            # 3. High confidence Entry Points
            elif file_p in high_conf_entry_files:
                category = "entry_point"
                confidence = "high"
                evidence.append("Identified as a high-confidence repository entry point")

            # 4. Frontend UI
            elif (
                any(p in ("frontend", "client", "web", "ui", "components", "views", "screens") for p in dir_parts)
                or base_name.endswith((".tsx", ".jsx", ".vue", ".svelte", ".html", ".css", ".scss"))
            ):
                category = "frontend"
                confidence = "high"
                evidence.append("Frontend client component or user interface asset")

            # 5. API Routes / Controllers
            elif (
                any(p in ("routes", "route", "controllers", "controller", "endpoints", "api", "handlers") for p in dir_parts)
                or any(
                    any(prefix in c.call_name for prefix in ("router.", "app.get", "app.post", "app.put", "app.delete"))
                    for c in pf.function_calls
                )
            ):
                category = "api_route"
                confidence = "high" if any(p in ("routes", "controllers", "endpoints") for p in dir_parts) else "medium"
                evidence.append("API endpoint, router, or request handler definition")

            # 6. Services / Business Logic
            elif (
                any(p in ("services", "service", "use_cases", "business", "domain") for p in dir_parts)
                or base_name in ("service.py", "services.py", "service.ts", "service.js")
                or base_name.endswith(("_service.py", "service.ts", "service.js"))
                or any(cls.name.endswith(("Service", "UseCase", "Manager")) for cls in pf.classes)
            ):
                category = "service"
                confidence = "high" if any(p in ("services", "service") for p in dir_parts) else "medium"
                evidence.append("Domain business logic service")

            # 7. Repositories / Data Access Objects
            elif (
                any(p in ("repository", "repositories", "dao", "store", "stores") for p in dir_parts)
                or base_name in ("repository.py", "repo.py", "store.py", "dao.py")
                or base_name.endswith(("_repo.py", "_repository.py", "repository.ts", "dao.java"))
                or any(cls.name.endswith(("Repository", "DAO", "Store")) for cls in pf.classes)
            ):
                category = "repository_or_dao"
                confidence = "high" if any(p in ("repository", "repositories", "dao", "store") for p in dir_parts) else "medium"
                evidence.append("Data access object or repository pattern")

            # 8. Database / Migrations
            elif (
                any(p in ("db", "database", "migrations", "alembic", "prisma", "typeorm", "sql") for p in dir_parts)
                or base_name in ("db.py", "database.py", "connection.py")
                or base_name.endswith((".sql", "schema.prisma"))
            ):
                category = "database"
                confidence = "high"
                evidence.append("Database schema, migration, or connection configuration")

            # 9. Models / Schemas
            elif (
                any(p in ("models", "model", "schemas", "schema", "entities", "entity", "types") for p in dir_parts)
                or base_name in ("models.py", "model.py", "schemas.py", "schema.py", "entities.py", "entity.py", "types.ts", "types.py")
                or base_name.endswith(("_model.py", "_models.py", "_schema.py", "_schemas.py"))
                or any(
                    any(
                        base in ("BaseModel", "Model", "Schema", "Entity", "Base")
                        or "model" in base.lower()
                        or "entity" in base.lower()
                        or "schema" in base.lower()
                        for base in cls.base_classes
                    )
                    for cls in pf.classes
                )
            ):
                category = "model"
                confidence = "high" if (
                    any(p in ("models", "schemas") for p in dir_parts)
                    or base_name in ("models.py", "model.py", "schemas.py", "schema.py")
                ) else "medium"
                evidence.append("Data model, schema, or entity definition")

            # 10. External Integrations / Clients / Adapters
            elif (
                any(p in ("integrations", "integration", "adapters", "adapter", "clients", "connectors") for p in dir_parts)
                or any(cls.name.endswith(("Client", "Adapter", "Connector", "Gateway")) for cls in pf.classes)
            ):
                category = "external_integration"
                confidence = "high" if any(p in ("integrations", "adapters") for p in dir_parts) else "medium"
                evidence.append("External service adapter or client integration")

            # 11. Utilities / Helpers
            elif (
                any(p in ("utils", "util", "helpers", "helper", "common", "shared", "lib", "tools") for p in dir_parts)
                or base_name in ("utils.py", "helpers.py", "common.py", "utils.ts", "helpers.ts")
            ):
                category = "utility"
                confidence = "high" if any(p in ("utils", "helpers") for p in dir_parts) else "medium"
                evidence.append("Shared utility or helper functions")

            # 12. Medium/Low Entry Points (fallback before unknown)
            elif file_p in all_entry_files:
                category = "entry_point"
                confidence = "medium"
                evidence.append("Identified as a candidate application entry point")

            # 13. Unknown (Strictly preserved, no invented labels)
            else:
                category = "unknown"
                confidence = "low"
                evidence.append("No specific architectural layer pattern matched")

            classified.append(
                ArchitecturalComponent(
                    file_path=file_p,
                    category=category,
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        return classified


component_classifier = ComponentClassifier()
