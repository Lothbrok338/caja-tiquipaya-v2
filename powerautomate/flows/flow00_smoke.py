"""Flujo 00 — Prueba HTTP Premium contra la API en Railway (sin lógica contable).

Disparador manual con 2 entradas: Caja y API key (texto seguro; no se guarda en
el paquete). Llama POST /v1/ping, valida status 200 + status=ok + eco del
correlation_id y deja un resultado legible en la ejecución.
"""

ENV_VARS = {
    "_prefijo": "gabo_",
    "_publisher": "cajasgabo",
    "gabo_ApiBaseUrl": {
        "display": "API Base URL (Railway)",
        "default": "https://REEMPLAZAR.up.railway.app",
    },
}

_SCHEMA_PING = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "caja": {"type": "string"},
        "correlation_id": {"type": "string"},
        "api": {"type": "string"},
        "engine_version": {"type": "string"},
        "timestamp_utc": {"type": "string"},
    },
}


def _definition(modo):
    if modo == "solution":
        pname = "API Base URL (gabo_ApiBaseUrl)"
        params = {pname: {"defaultValue": ENV_VARS["gabo_ApiBaseUrl"]["default"], "type": "String",
                          "metadata": {"schemaName": "gabo_ApiBaseUrl"}}}
    else:
        pname = "ApiBaseUrl"
        params = {pname: {"defaultValue": ENV_VARS["gabo_ApiBaseUrl"]["default"], "type": "String"}}
    params["$connections"] = {"defaultValue": {}, "type": "Object"}
    params["$authentication"] = {"defaultValue": {}, "type": "SecureObject"}

    return {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "parameters": params,
        "triggers": {
            "manual": {
                "type": "Request",
                "kind": "Button",
                "inputs": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "text": {"title": "Caja", "type": "string", "x-ms-dynamically-added": True,
                                     "description": "Ej.: AYACUCHO", "x-ms-content-hint": "TEXT"},
                            "text_1": {"title": "API key", "type": "string", "x-ms-dynamically-added": True,
                                       "description": "Clave de la API (no se guarda en el flujo)",
                                       "x-ms-content-hint": "TEXT"},
                        },
                        "required": ["text", "text_1"],
                    }
                },
            }
        },
        "actions": {
            "CorrelationId": {"type": "Compose", "inputs": "@guid()", "runAfter": {}},
            "HTTP_ping": {
                "type": "Http",
                "runAfter": {"CorrelationId": ["Succeeded"]},
                "inputs": {
                    "method": "POST",
                    "uri": f"@concat(parameters('{pname}'), '/v1/ping')",
                    "headers": {
                        "Content-Type": "application/json",
                        "X-API-Key": "@triggerBody()?['text_1']",
                        "X-Correlation-Id": "@outputs('CorrelationId')",
                    },
                    "body": {"caja": "@triggerBody()?['text']"},
                    "retryPolicy": {"type": "fixed", "count": 2, "interval": "PT10S"},
                },
                "runtimeConfiguration": {"secureData": {"properties": ["inputs"]}},
            },
            "Parse_JSON": {
                "type": "ParseJson",
                "runAfter": {"HTTP_ping": ["Succeeded"]},
                "inputs": {"content": "@body('HTTP_ping')", "schema": _SCHEMA_PING},
            },
            "Condicion_respuesta_valida": {
                "type": "If",
                "runAfter": {"Parse_JSON": ["Succeeded"]},
                "expression": {
                    "and": [
                        {"equals": ["@outputs('HTTP_ping')['statusCode']", 200]},
                        {"equals": ["@body('Parse_JSON')?['status']", "ok"]},
                        {"equals": ["@body('Parse_JSON')?['correlation_id']", "@outputs('CorrelationId')"]},
                    ]
                },
                "actions": {
                    "Resultado_OK": {
                        "type": "Compose",
                        "runAfter": {},
                        "inputs": "OK | caja=@{body('Parse_JSON')?['caja']} | engine=@{body('Parse_JSON')?['engine_version']} | corr=@{body('Parse_JSON')?['correlation_id']}",
                    }
                },
                "else": {
                    "actions": {
                        "Terminar_con_error": {
                            "type": "Terminate",
                            "runAfter": {},
                            "inputs": {
                                "runStatus": "Failed",
                                "runError": {
                                    "code": "RESPUESTA_API_INVALIDA",
                                    "message": "@{concat('La API respondió pero no cumple el contrato. correlation_id esperado=', outputs('CorrelationId'))}",
                                },
                            },
                        }
                    }
                },
            },
        },
    }


FLOW = {
    "id": "Flujo00_Smoke_HTTP",
    "display_name": "CAJAS GABO - 00 Prueba HTTP Railway",
    "description": "Smoke test HTTP Premium -> API Python en Railway. Sin lógica contable.",
    "definition": _definition,
}
