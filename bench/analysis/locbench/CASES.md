# Case studies (EXPLORATORY, POST-HOC; factual sheets for ANALYSIS.md section I)

## added: `Agenta-AI__agenta-1639` (Performance Issue; method bm25-graph)

- Issue (first 300 characters): [AGE-164] [Improvement] Speed up the endpoint /get_config The call to retrieve the configuration takes 1.20 seconds, indicating that 'get_config' is highly unoptimised. Here's the current process: * It fetches the base_id. * It checks permissions. * It lists the environment for the app_id, which is 
- Gold files: agenta-backend/agenta_backend/models/converters.py, agenta-backend/agenta_backend/routers/configs_router.py, agenta-backend/agenta_backend/services/db_manager.py
- Focus gold file: `agenta-backend/agenta_backend/models/converters.py`
- File-BM25 top 10: **agenta-backend/agenta_backend/services/db_manager.py**, **agenta-backend/agenta_backend/routers/configs_router.py**, agenta-backend/agenta_backend/routers/variants_router.py, agenta-cli/agenta/client/client.py, agenta-cli/agenta/cli/variant_commands.py, agenta-cli/agenta/client/backend/resources/evaluators/client.py, agenta-backend/agenta_backend/routers/evaluators_router.py, agenta-cli/agenta/client/backend/resources/apps/client.py, agenta-backend/agenta_backend/routers/app_router.py, agenta-cli/agenta/client/backend/resources/variants/client.py
- rhizome-search [v0.2] top 10: **agenta-backend/agenta_backend/services/db_manager.py**, agenta-backend/agenta_backend/routers/variants_router.py, **agenta-backend/agenta_backend/routers/configs_router.py**, agenta-cli/agenta/client/client.py, agenta-cli/agenta/cli/variant_commands.py, agenta-backend/agenta_backend/routers/evaluators_router.py, agenta-cli/agenta/client/backend/resources/evaluators/client.py, agenta-backend/agenta_backend/routers/app_router.py, agenta-cli/agenta/client/backend/resources/apps/client.py, agenta-cli/agenta/client/backend/resources/variants/client.py
- rhizome-ctx-cat [v0.2] top 10: **agenta-backend/agenta_backend/services/db_manager.py**, agenta-backend/agenta_backend/routers/variants_router.py, **agenta-backend/agenta_backend/routers/configs_router.py**, agenta-cli/agenta/client/client.py, agenta-cli/agenta/cli/variant_commands.py, agenta-backend/agenta_backend/routers/evaluators_router.py, agenta-cli/agenta/client/backend/resources/evaluators/client.py, agenta-backend/agenta_backend/routers/app_router.py, agenta-cli/agenta/client/backend/resources/apps/client.py, agenta-cli/agenta/client/backend/resources/variants/client.py
- bm25-graph top 10: **agenta-backend/agenta_backend/services/db_manager.py**, **agenta-backend/agenta_backend/routers/configs_router.py**, agenta-backend/agenta_backend/routers/variants_router.py, agenta-cli/agenta/client/client.py, agenta-backend/agenta_backend/models/db_models.py, agenta-backend/agenta_backend/utils/common.py, **agenta-backend/agenta_backend/models/converters.py**, agenta-backend/agenta_backend/services/json_importer_helper.py, agenta-backend/agenta_backend/services/app_manager.py, agenta-backend/agenta_backend/services/logs_manager.py
- v0.2 entry points: agenta-backend/agenta_backend/services/db_manager.py, agenta-backend/agenta_backend/routers/variants_router.py, agenta-backend/agenta_backend/routers/configs_router.py, agenta-cli/agenta/client/client.py; strong band 40
- PPR top 10 (v0.2 ctx-cat): agenta-backend/agenta_backend/models/db_models.py, agenta-backend/agenta_backend/utils/common.py, agenta-cli/agenta/client/api_models.py, agenta-backend/agenta_backend/services/app_manager.py, agenta-backend/agenta_backend/tasks/evaluations.py, agenta-backend/agenta_backend/main.py, agenta-backend/agenta_backend/services/evaluation_service.py, agenta-backend/agenta_backend/routers/app_router.py, **agenta-backend/agenta_backend/models/converters.py**, agenta-cli/agenta/cli/variant_commands.py
- Shortest import path from a v0.2 entry point to the focus gold file: agenta-backend/agenta_backend/models/converters.py <- agenta-backend/agenta_backend/services/db_manager.py

## added: `AzureAD__microsoft-authentication-library-for-python-454` (Performance Issue; method bm25-graph)

- Issue (first 300 characters): MSAL can consider using lazy import for `request`, `jwt` **Describe the bug** Importing MSAL is can cost ~300ms on Windows due to some heavy libraries like `request` and `jwt`: ``` python -X importtime -c "import msal" 2>perf.log; tuna .\perf.log ``` ![image](https://user-images.githubusercontent.co
- Gold files: msal/application.py, msal/authority.py, msal/oauth2cli/assertion.py, msal/oauth2cli/oauth2.py
- Focus gold file: `msal/authority.py`
- File-BM25 top 10: **msal/application.py**, sample/vault_jwt_sample.py, sample/confidential_client_secret_sample.py, sample/confidential_client_certificate_sample.py, sample/migrate_rt.py, sample/interactive_sample.py, sample/username_password_sample.py, msal/token_cache.py, setup.py, sample/device_flow_sample.py
- rhizome-search [v0.2] top 10: **msal/application.py**, sample/vault_jwt_sample.py, msal/oauth2cli/authcode.py, sample/confidential_client_secret_sample.py, sample/confidential_client_certificate_sample.py, msal/oauth2cli/http.py, sample/migrate_rt.py, msal/region.py, sample/interactive_sample.py, **msal/oauth2cli/oauth2.py**
- rhizome-ctx-cat [v0.2] top 10: **msal/application.py**, sample/vault_jwt_sample.py, msal/oauth2cli/authcode.py, sample/confidential_client_secret_sample.py, sample/confidential_client_certificate_sample.py, msal/oauth2cli/http.py, sample/migrate_rt.py, msal/region.py, sample/interactive_sample.py, **msal/oauth2cli/oauth2.py**
- bm25-graph top 10: **msal/application.py**, sample/vault_jwt_sample.py, sample/confidential_client_secret_sample.py, sample/confidential_client_certificate_sample.py, msal/telemetry.py, msal/token_cache.py, **msal/authority.py**, msal/oauth2cli/oidc.py, **msal/oauth2cli/assertion.py**, msal/region.py
- v0.2 entry points: msal/application.py, sample/vault_jwt_sample.py, msal/oauth2cli/authcode.py, sample/confidential_client_secret_sample.py; strong band 16
- PPR top 10 (v0.2 ctx-cat): msal/__init__.py, **msal/oauth2cli/oauth2.py**, msal/token_cache.py, msal/oauth2cli/oidc.py, **msal/authority.py**, msal/telemetry.py, sample/confidential_client_certificate_sample.py, sample/migrate_rt.py, sample/interactive_sample.py, sample/username_password_sample.py
- Shortest import path from a v0.2 entry point to the focus gold file: msal/authority.py <- msal/application.py

## added: `Deltares__imod-python-1159` (Performance Issue; method bm25-graph)

- Issue (first 300 characters): Bottlenecks writing HFBs LHM https://github.com/Deltares/imod-python/pull/1157 considerably improves the speed with which the LHM is written: From 34 minutes to 12.5 minutes. This is still slower than expected however. Based on profiling, I've identified 3 main bottlenecks: - 4.5 minutes: ``xu.DataA
- Gold files: imod/mf6/simulation.py, imod/schemata.py, imod/typing/grid.py
- Focus gold file: `imod/typing/grid.py`
- File-BM25 top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/package.py, imod/mf6/model.py, **imod/mf6/simulation.py**, imod/mf6/wel.py, imod/mf6/riv.py, **imod/schemata.py**, imod/prepare/regrid.py
- rhizome-search [v0.2] top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py, imod/mf6/package.py, imod/mf6/riv.py, imod/mf6/model.py, imod/prepare/regrid.py, **imod/mf6/simulation.py**, **imod/schemata.py**
- rhizome-ctx-cat [v0.2] top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py, imod/mf6/package.py, imod/mf6/riv.py, imod/mf6/model.py, imod/prepare/regrid.py, **imod/mf6/simulation.py**, **imod/schemata.py**
- bm25-graph top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/package.py, **imod/typing/grid.py**, imod/mf6/utilities/regridding_types.py, imod/mf6/interfaces/imodel.py, imod/mf6/interfaces/iregridpackage.py, imod/mf6/regrid/regrid_schemes.py, imod/mf6/interfaces/ilinedatapackage.py
- v0.2 entry points: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py; strong band 54
- PPR top 10 (v0.2 ctx-cat): imod/__init__.py, **imod/schemata.py**, imod/mf6/regrid/regrid_schemes.py, imod/typing/__init__.py, **imod/typing/grid.py**, imod/mf6/utilities/regridding_types.py, imod/mf6/package.py, **imod/mf6/simulation.py**, imod/mf6/validation.py, examples/user-guide/09-topsystem.py
- Shortest import path from a v0.2 entry point to the focus gold file: imod/typing/grid.py <- imod/mf6/utilities/regrid.py

## added: `Innopoints__backend-124` (Security Vulnerability; method rhizome-ctx-cat [v0.2])

- Issue (first 300 characters): Implement CSRF protection
- Gold files: innopoints/blueprints.py, innopoints/core/helpers.py, innopoints/schemas/account.py, innopoints/views/account.py, innopoints/views/authentication.py
- Focus gold file: `innopoints/views/account.py`
- File-BM25 top 10: innopoints/extensions.py, run.py, innopoints/__init__.py, innopoints/app.py, **innopoints/blueprints.py**, innopoints/config/common.py, innopoints/config/dev.py, innopoints/config/prod.py, **innopoints/core/helpers.py**, innopoints/core/sql_hacks.py
- rhizome-search [v0.2] top 10: innopoints/extensions.py, run.py, innopoints/__init__.py, innopoints/app.py, **innopoints/blueprints.py**, innopoints/config/common.py, innopoints/config/dev.py, innopoints/config/prod.py, **innopoints/core/helpers.py**, innopoints/core/sql_hacks.py
- rhizome-ctx-cat [v0.2] top 10: innopoints/extensions.py, innopoints/models/__init__.py, **innopoints/core/helpers.py**, **innopoints/views/account.py**, innopoints/views/application.py, innopoints/views/project.py, innopoints/views/variety.py, innopoints/models/activity.py, innopoints/models/variety.py, innopoints/views/product.py
- bm25-graph top 10: innopoints/extensions.py, run.py, innopoints/__init__.py, innopoints/app.py, **innopoints/blueprints.py**, innopoints/config/common.py, innopoints/config/dev.py, innopoints/config/prod.py, **innopoints/core/helpers.py**, innopoints/core/sql_hacks.py
- v0.2 entry points: innopoints/extensions.py; strong band 1
- PPR top 10 (v0.2 ctx-cat): innopoints/models/__init__.py, **innopoints/core/helpers.py**, **innopoints/views/account.py**, innopoints/views/application.py, innopoints/views/project.py, innopoints/views/variety.py, innopoints/models/activity.py, innopoints/models/variety.py, innopoints/views/product.py, innopoints/views/activity.py
- Shortest import path from a v0.2 entry point to the focus gold file: innopoints/views/account.py <- innopoints/extensions.py

## pushed out: `BerriAI__litellm-6563` (Bug Report; method bm25-graph)

- Issue (first 300 characters): [Bug]: Langfuse Integration Error: TypeError: cannot pickle '_thread.RLock' object ### What happened When using the Langfuse integration with litellm.log_langfuse_v2, a TypeError: cannot pickle '_thread.RLock' object is raised during the logging process. This appears to be caused by attempting to de
- Gold files: litellm/integrations/langfuse/langfuse.py
- Focus gold file: `litellm/integrations/langfuse/langfuse.py`
- File-BM25 top 10: litellm/llms/palm.py, litellm/llms/gemini.py, litellm/llms/bedrock/chat/converse_transformation.py, litellm/litellm_core_utils/litellm_logging.py, **litellm/integrations/langfuse/langfuse.py**, litellm/llms/ollama.py, litellm/litellm_core_utils/redact_messages.py, litellm/llms/huggingface_restapi.py, litellm/proxy/litellm_pre_call_utils.py, litellm/utils.py
- rhizome-search [v0.2] top 10: litellm/litellm_core_utils/litellm_logging.py, litellm/proxy/utils.py, **litellm/integrations/langfuse/langfuse.py**, litellm/integrations/braintrust_logging.py, litellm/llms/bedrock/chat/converse_transformation.py, litellm/llms/huggingface_restapi.py, litellm/llms/anthropic/chat/handler.py, litellm/llms/ollama.py, litellm/proxy/litellm_pre_call_utils.py, litellm/llms/palm.py
- rhizome-ctx-cat [v0.2] top 10: litellm/litellm_core_utils/litellm_logging.py, litellm/proxy/utils.py, **litellm/integrations/langfuse/langfuse.py**, litellm/integrations/braintrust_logging.py, litellm/llms/bedrock/chat/converse_transformation.py, litellm/llms/huggingface_restapi.py, litellm/llms/anthropic/chat/handler.py, litellm/llms/ollama.py, litellm/proxy/litellm_pre_call_utils.py, litellm/llms/palm.py
- bm25-graph top 10: litellm/llms/palm.py, litellm/llms/gemini.py, litellm/llms/bedrock/chat/converse_transformation.py, litellm/litellm_core_utils/litellm_logging.py, litellm/utils.py, litellm/proxy/pass_through_endpoints/types.py, litellm/litellm_core_utils/llm_cost_calc/google.py, litellm/__init__.py, litellm/_logging.py, litellm/llms/prompt_templates/factory.py
- v0.2 entry points: litellm/litellm_core_utils/litellm_logging.py, litellm/proxy/utils.py, litellm/integrations/langfuse/langfuse.py, litellm/integrations/braintrust_logging.py; strong band 34
- PPR top 10 (v0.2 ctx-cat): litellm/__init__.py, litellm/proxy/proxy_server.py, litellm/_logging.py, litellm/utils.py, litellm/types/integrations/langfuse.py, litellm/proxy/_types.py, litellm/types/utils.py, litellm/main.py, litellm/types/llms/openai.py, litellm/integrations/langfuse/langfuse_handler.py
- Shortest import path from a v0.2 entry point to the focus gold file: litellm/integrations/langfuse/langfuse.py

## pushed out: `Chainlit__chainlit-1575` (Security Vulnerability; method bm25-graph)

- Issue (first 300 characters): Security: allowed origins should not be * by default CORS headers should be restricted to the current domain at least, by default.
- Gold files: backend/chainlit/config.py, backend/chainlit/server.py, backend/chainlit/socket.py
- Focus gold file: `backend/chainlit/socket.py`
- File-BM25 top 10: **backend/chainlit/server.py**, **backend/chainlit/config.py**, backend/chainlit/oauth_providers.py, backend/chainlit/auth.py, backend/chainlit/callbacks.py, backend/chainlit/session.py, backend/chainlit/user.py, **backend/chainlit/socket.py**, backend/chainlit/langchain/callbacks.py, backend/chainlit/markdown.py
- rhizome-search [v0.2] top 10: **backend/chainlit/server.py**, **backend/chainlit/config.py**, backend/chainlit/oauth_providers.py, backend/chainlit/session.py, backend/chainlit/auth.py, backend/chainlit/callbacks.py, backend/chainlit/user.py, **backend/chainlit/socket.py**, backend/chainlit/langchain/callbacks.py, backend/chainlit/llama_index/callbacks.py
- rhizome-ctx-cat [v0.2] top 10: **backend/chainlit/server.py**, backend/chainlit/oauth_providers.py, **backend/chainlit/config.py**, **backend/chainlit/socket.py**, backend/chainlit/auth.py, backend/chainlit/user.py, backend/chainlit/callbacks.py, backend/chainlit/cli/__init__.py, backend/chainlit/__init__.py, backend/chainlit/context.py
- bm25-graph top 10: **backend/chainlit/server.py**, **backend/chainlit/config.py**, backend/chainlit/oauth_providers.py, backend/chainlit/auth.py, backend/chainlit/user.py, backend/chainlit/data/__init__.py, backend/chainlit/logger.py, backend/chainlit/types.py, backend/chainlit/data/acl.py, backend/chainlit/_utils.py
- v0.2 entry points: backend/chainlit/server.py, backend/chainlit/oauth_providers.py; strong band 2
- PPR top 10 (v0.2 ctx-cat): **backend/chainlit/config.py**, **backend/chainlit/socket.py**, backend/chainlit/auth.py, backend/chainlit/user.py, backend/chainlit/callbacks.py, backend/chainlit/cli/__init__.py, backend/chainlit/__init__.py, backend/chainlit/context.py, backend/chainlit/discord/app.py, backend/chainlit/message.py
- Shortest import path from a v0.2 entry point to the focus gold file: backend/chainlit/socket.py <- backend/chainlit/server.py

## pushed out: `DS4SD__docling-314` (Bug Report; method bm25-graph)

- Issue (first 300 characters): Missing Text Inside Tables When Converting from DOCX to Markdown ### Bug I've encountered an issue with Docling version 2.4.2 while converting a DOCX file to Markdown. It seems that the conversion process is missing text inside tables. **Command Used:** ```sh docling example.docx --from docx --to md
- Gold files: docling/backend/msword_backend.py
- Focus gold file: `docling/backend/msword_backend.py`
- File-BM25 top 10: docling/cli/main.py, docling/models/tesseract_ocr_model.py, docling/models/tesseract_ocr_cli_model.py, docling/datamodel/base_models.py, **docling/backend/msword_backend.py**, docs/examples/run_with_formats.py, docs/examples/batch_convert.py, docling/datamodel/pipeline_options.py, docling/backend/md_backend.py, docling/document_converter.py
- rhizome-search [v0.2] top 10: docling/cli/main.py, docs/examples/run_with_formats.py, docling/models/tesseract_ocr_model.py, docling/models/tesseract_ocr_cli_model.py, docling/datamodel/base_models.py, **docling/backend/msword_backend.py**, docs/examples/batch_convert.py, docs/examples/export_figures.py, docs/examples/custom_convert.py, docling/datamodel/pipeline_options.py
- rhizome-ctx-cat [v0.2] top 10: docling/cli/main.py, docs/examples/run_with_formats.py, docling/models/tesseract_ocr_model.py, docling/models/tesseract_ocr_cli_model.py, docling/datamodel/base_models.py, **docling/backend/msword_backend.py**, docs/examples/batch_convert.py, docs/examples/export_figures.py, docs/examples/custom_convert.py, docling/datamodel/pipeline_options.py
- bm25-graph top 10: docling/cli/main.py, docling/models/tesseract_ocr_model.py, docling/models/tesseract_ocr_cli_model.py, docling/datamodel/base_models.py, docling/datamodel/pipeline_options.py, docling/document_converter.py, docling/backend/docling_parse_backend.py, docling/backend/docling_parse_v2_backend.py, docling/backend/pdf_backend.py, docling/backend/pypdfium2_backend.py
- v0.2 entry points: docling/cli/main.py, docs/examples/run_with_formats.py, docling/models/tesseract_ocr_model.py, docling/models/tesseract_ocr_cli_model.py; strong band 10
- PPR top 10 (v0.2 ctx-cat): docling/datamodel/base_models.py, docling/document_converter.py, docling/datamodel/document.py, docling/datamodel/pipeline_options.py, docling/pipeline/standard_pdf_pipeline.py, docling/pipeline/base_pipeline.py, docling/datamodel/settings.py, docling/pipeline/simple_pipeline.py, docling/utils/profiling.py, docling/models/layout_model.py
- Shortest import path from a v0.2 entry point to the focus gold file: docling/backend/msword_backend.py <- docling/datamodel/base_models.py <- docling/cli/main.py

## pushed out: `Deltares__imod-python-1159` (Performance Issue; method bm25-graph)

- Issue (first 300 characters): Bottlenecks writing HFBs LHM https://github.com/Deltares/imod-python/pull/1157 considerably improves the speed with which the LHM is written: From 34 minutes to 12.5 minutes. This is still slower than expected however. Based on profiling, I've identified 3 main bottlenecks: - 4.5 minutes: ``xu.DataA
- Gold files: imod/mf6/simulation.py, imod/schemata.py, imod/typing/grid.py
- Focus gold file: `imod/mf6/simulation.py`
- File-BM25 top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/package.py, imod/mf6/model.py, **imod/mf6/simulation.py**, imod/mf6/wel.py, imod/mf6/riv.py, **imod/schemata.py**, imod/prepare/regrid.py
- rhizome-search [v0.2] top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py, imod/mf6/package.py, imod/mf6/riv.py, imod/mf6/model.py, imod/prepare/regrid.py, **imod/mf6/simulation.py**, **imod/schemata.py**
- rhizome-ctx-cat [v0.2] top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py, imod/mf6/package.py, imod/mf6/riv.py, imod/mf6/model.py, imod/prepare/regrid.py, **imod/mf6/simulation.py**, **imod/schemata.py**
- bm25-graph top 10: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/package.py, **imod/typing/grid.py**, imod/mf6/utilities/regridding_types.py, imod/mf6/interfaces/imodel.py, imod/mf6/interfaces/iregridpackage.py, imod/mf6/regrid/regrid_schemes.py, imod/mf6/interfaces/ilinedatapackage.py
- v0.2 entry points: imod/mf6/utilities/regrid.py, examples/user-guide/06-lazy-evaluation.py, examples/user-guide/08-regridding.py, imod/mf6/wel.py; strong band 54
- PPR top 10 (v0.2 ctx-cat): imod/__init__.py, **imod/schemata.py**, imod/mf6/regrid/regrid_schemes.py, imod/typing/__init__.py, **imod/typing/grid.py**, imod/mf6/utilities/regridding_types.py, imod/mf6/package.py, **imod/mf6/simulation.py**, imod/mf6/validation.py, examples/user-guide/09-topsystem.py
- Shortest import path from a v0.2 entry point to the focus gold file: imod/mf6/simulation.py <- imod/mf6/utilities/regrid.py

## unreachable: `Standard-Labs__real-intent-102` (Performance Issue; method rhizome-ctx-cat [v0.2])

- Issue (first 300 characters): Improve integration efficiency Multithreading
- Gold files: real_intent/deliver/followupboss/vanilla.py, real_intent/deliver/kvcore/__init__.py
- Focus gold file: `real_intent/deliver/followupboss/vanilla.py`
- File-BM25 top 10: real_intent/__init__.py, real_intent/client.py, real_intent/error.py, real_intent/internal_logging.py, real_intent/schemas.py, real_intent/taxonomy.py, real_intent/analyze/__init__.py, real_intent/analyze/base.py, real_intent/analyze/insights/__init__.py, real_intent/analyze/insights/many.py
- rhizome-search [v0.2] top 10: real_intent/__init__.py, real_intent/client.py, real_intent/error.py, real_intent/internal_logging.py, real_intent/schemas.py, real_intent/taxonomy.py, real_intent/analyze/__init__.py, real_intent/analyze/base.py, real_intent/analyze/insights/__init__.py, real_intent/analyze/insights/many.py
- rhizome-ctx-cat [v0.2] top 10: real_intent/__init__.py, real_intent/client.py, real_intent/error.py, real_intent/internal_logging.py, real_intent/schemas.py, real_intent/taxonomy.py, real_intent/analyze/__init__.py, real_intent/analyze/base.py, real_intent/analyze/insights/__init__.py, real_intent/analyze/insights/many.py
- bm25-graph top 10: real_intent/__init__.py, real_intent/client.py, real_intent/error.py, real_intent/internal_logging.py, real_intent/schemas.py, real_intent/taxonomy.py, real_intent/analyze/__init__.py, real_intent/analyze/base.py, real_intent/analyze/insights/__init__.py, real_intent/analyze/insights/many.py
- v0.2 entry points: ; strong band 0
- PPR top 10 (v0.2 ctx-cat): 
- Shortest import path from a v0.2 entry point to the focus gold file: no path from any v0.2 entry point

## unreachable: `TagStudioDev__TagStudio-735` (Performance Issue; method rhizome-ctx-cat [v0.2])

- Issue (first 300 characters): [Bug]: Adding (or searching for) tags gets increasingly slower in the same session (running process) ### Checklist - [x] I am using an up-to-date version. - [x] I have read the [documentation](https://github.com/TagStudioDev/TagStudio/blob/main/docs/index.md). - [x] I have searched existing [issues]
- Gold files: tagstudio/src/qt/modals/tag_search.py, tagstudio/src/qt/widgets/tag.py
- Focus gold file: `tagstudio/src/qt/widgets/tag.py`
- File-BM25 top 10: tagstudio/src/core/library/json/library.py, tagstudio/src/qt/ts_qt.py, tagstudio/src/core/library/alchemy/library.py, tagstudio/src/qt/helpers/vendored/pydub/audio_segment.py, tagstudio/src/core/ts_core.py, tagstudio/src/core/library/alchemy/visitors.py, tagstudio/src/qt/modals/folders_to_tags.py, **tagstudio/src/qt/modals/tag_search.py**, tagstudio/src/core/library/alchemy/enums.py, tagstudio/src/qt/widgets/tag_box.py
- rhizome-search [v0.2] top 10: tagstudio/src/core/library/json/library.py, tagstudio/src/qt/ts_qt.py, tagstudio/src/core/library/alchemy/library.py, tagstudio/src/qt/helpers/vendored/pydub/audio_segment.py, tagstudio/src/core/ts_core.py, tagstudio/src/qt/modals/folders_to_tags.py, tagstudio/src/core/library/alchemy/enums.py, tagstudio/src/core/library/alchemy/visitors.py, **tagstudio/src/qt/modals/tag_search.py**, tagstudio/tag_studio.py
- rhizome-ctx-cat [v0.2] top 10: tagstudio/src/core/library/json/library.py, tagstudio/src/qt/ts_qt.py, tagstudio/src/core/library/alchemy/library.py, tagstudio/src/qt/helpers/vendored/pydub/audio_segment.py, tagstudio/src/core/ts_core.py, tagstudio/src/core/library/json/fields.py, tagstudio/src/core/library/alchemy/models.py, tagstudio/src/core/library/alchemy/fields.py, tagstudio/src/core/library/alchemy/enums.py, tagstudio/src/core/library/alchemy/visitors.py
- bm25-graph top 10: tagstudio/src/core/library/json/library.py, tagstudio/src/qt/ts_qt.py, tagstudio/src/core/library/alchemy/library.py, tagstudio/src/qt/helpers/vendored/pydub/audio_segment.py, tagstudio/src/core/library/json/fields.py, tagstudio/src/core/library/alchemy/models.py, tagstudio/src/core/constants.py, tagstudio/src/core/enums.py, tagstudio/src/core/library/alchemy/fields.py, tagstudio/src/core/library/alchemy/enums.py
- v0.2 entry points: tagstudio/src/core/library/json/library.py, tagstudio/src/qt/ts_qt.py, tagstudio/src/core/library/alchemy/library.py, tagstudio/src/qt/helpers/vendored/pydub/audio_segment.py; strong band 5
- PPR top 10 (v0.2 ctx-cat): tagstudio/src/core/library/json/fields.py, tagstudio/src/core/library/alchemy/models.py, tagstudio/src/core/library/alchemy/fields.py, tagstudio/src/core/library/alchemy/enums.py, tagstudio/src/core/library/alchemy/visitors.py, tagstudio/src/core/constants.py, tagstudio/src/core/library/alchemy/joins.py, tagstudio/src/core/enums.py, tagstudio/src/core/library/alchemy/db.py, tagstudio/src/core/library/alchemy/__init__.py
- Shortest import path from a v0.2 entry point to the focus gold file: no path from any v0.2 entry point
