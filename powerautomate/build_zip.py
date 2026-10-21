"""powerautomate/build_zip.py — genera ZIP importables de Power Automate.

Dos formatos, MISMA definición de flujo:
  legacy    -> Mis flujos > Importar > Importar paquete (heredado)
  solution  -> Soluciones > Importar solución (requiere Dataverse)

Build determinístico: GUIDs por uuid5 y fecha fija -> mismo código = mismo ZIP.
No incorpora credenciales: la API key entra como parámetro SEGURO del trigger.

Uso: python powerautomate/build_zip.py [--version 0.1.0] [--out powerautomate/dist]
"""

import argparse
import json
import os
import re
import sys
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flows.flow00_smoke import FLOW, ENV_VARS  # noqa: E402

_NS = uuid.UUID("6f1f2c1e-0a7b-4c55-9a58-3b0f0c1d2e00")
_FECHA = "2026-01-01T00:00:00Z"
_ZIP_FECHA = (2026, 1, 1, 0, 0, 0)
SCHEMA_WF = "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"


def guid(*partes):
    return str(uuid.uuid5(_NS, "|".join(partes)))


# ---------------------------------------------------------------- validación
def validar_definicion(defn, nombre):
    """Chequeos estáticos: runAfter y referencias outputs()/body()/actions()
    deben apuntar a acciones existentes; parámetros usados deben estar declarados."""
    errores = []
    nombres = set()

    def recolectar(acciones):
        for n, a in acciones.items():
            nombres.add(n)
            for sub in ("actions",):
                recolectar(a.get(sub, {}))
            if "else" in a:
                recolectar(a["else"].get("actions", {}))

    recolectar(defn.get("actions", {}))
    texto = json.dumps(defn)
    for ref in re.findall(r"(?:outputs|body|actions)\('([^']+)'\)", texto):
        if ref not in nombres:
            errores.append(f"referencia a acción inexistente: {ref}")
    for ref in re.findall(r"triggerBody\(\)|triggerOutputs\(\)", texto):
        if not defn.get("triggers"):
            errores.append("usa trigger* sin trigger")
    for p in set(re.findall(r"parameters\('([^']+)'\)", texto)):
        if p not in defn.get("parameters", {}):
            errores.append(f"parámetro no declarado: {p}")

    def runafter(acciones, ambito):
        for n, a in acciones.items():
            for dep in a.get("runAfter", {}):
                if dep not in acciones:
                    errores.append(f"runAfter de {n} apunta a {dep} (fuera de {ambito})")
            runafter(a.get("actions", {}), n)
            if "else" in a:
                runafter(a["else"].get("actions", {}), n)

    runafter(defn.get("actions", {}), "raíz")
    if re.search(r"(?i)(bearer\s+[a-z0-9]|password|secret\s*[:=]|sig=)", texto):
        errores.append("posible credencial embebida")
    if errores:
        raise ValueError(f"{nombre}: " + "; ".join(errores))


# ---------------------------------------------------------------- legacy
def construir_legacy(flow, version):
    fid = guid("flow", flow["id"])
    defn = flow["definition"](modo="legacy")
    validar_definicion(defn, flow["id"])
    manifest = {
        "schema": "1.0",
        "details": {
            "displayName": flow["display_name"],
            "description": flow["description"],
            "createdTime": _FECHA,
            "packageTelemetryId": guid("pkg", flow["id"], version),
            "creator": "N/A",
            "sourceEnvironment": "/providers/Microsoft.ProcessSimple/environments/Default-00000000-0000-0000-0000-000000000000",
        },
        "resources": {
            fid: {
                "type": "Microsoft.Flow/flows",
                "suggestedCreationType": "New",
                "creationType": "New, Update",
                "details": {"displayName": flow["display_name"]},
                "configurableBy": "User",
                "hierarchy": "Root",
                "dependsOn": [],
            }
        },
    }
    flow_json = {
        "name": fid,
        "id": f"/providers/Microsoft.Flow/flows/{fid}",
        "type": "Microsoft.Flow/flows",
        "properties": {
            "apiId": "/providers/Microsoft.PowerApps/apis/shared_logicflows",
            "displayName": flow["display_name"],
            "definition": defn,
            "connectionReferences": {},
            "flowFailureAlertSubscribed": False,
            "isManaged": False,
        },
    }
    base = f"Microsoft.Flow/flows/{fid}"
    return {
        "manifest.json": manifest,
        "Microsoft.Flow/flows/manifest.json": {fid: {"id": f"/providers/Microsoft.Flow/flows/{fid}", "type": "Microsoft.Flow/flows"}},
        f"{base}/definition.json": flow_json,
        f"{base}/apisMap.json": {},
        f"{base}/connectionsMap.json": {},
    }


# ---------------------------------------------------------------- solución
def _xml_esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def construir_solution(flow, version):
    wid = guid("wf", flow["id"]).upper()
    defn = flow["definition"](modo="solution")
    validar_definicion(defn, flow["id"])
    pfx = ENV_VARS["_prefijo"]
    uniq = f"{pfx}CajasGaboSmoke"
    wf_json = {"properties": {"connectionReferences": {}, "definition": defn, "templateName": None}, "schemaVersion": "1.0.0.0"}
    wf_file = f"Workflows/{flow['id']}-{wid}.json"
    nombre = _xml_esc(flow["display_name"])
    ev_roots = "".join(
        f'<RootComponent type="380" schemaName="{k}" behavior="0" />' for k in ENV_VARS if not k.startswith("_")
    )
    solution_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.2.0.0" SolutionPackageVersion="9.2" languagecode="3082" generatedBy="CajasGabo" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>{uniq}</UniqueName>
    <LocalizedNames><LocalizedName description="CAJAS GABO - Smoke" languagecode="3082" /></LocalizedNames>
    <Descriptions />
    <Version>{version}.0</Version>
    <Managed>0</Managed>
    <Publisher>
      <UniqueName>{ENV_VARS['_publisher']}</UniqueName>
      <LocalizedNames><LocalizedName description="CAJAS GABO" languagecode="3082" /></LocalizedNames>
      <Descriptions />
      <EMailAddress xsi:nil="true" /><SupportingWebsiteUrl xsi:nil="true" />
      <CustomizationPrefix>{pfx.rstrip('_')}</CustomizationPrefix>
      <CustomizationOptionValuePrefix>10000</CustomizationOptionValuePrefix>
      <Addresses />
    </Publisher>
    <RootComponents>
      <RootComponent type="29" id="{{{wid}}}" behavior="0" />
      {ev_roots}
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>
"""
    customizations = f"""<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entities></Entities>
  <Roles></Roles>
  <Workflows>
    <Workflow WorkflowId="{{{wid.lower()}}}" Name="{nombre}">
      <JsonFileName>/{wf_file}</JsonFileName>
      <Type>1</Type><Subprocess>0</Subprocess><Category>5</Category><Mode>0</Mode><Scope>4</Scope>
      <OnDemand>0</OnDemand><TriggerOnCreate>0</TriggerOnCreate><TriggerOnDelete>0</TriggerOnDelete>
      <AsyncAutodelete>0</AsyncAutodelete><SyncWorkflowLogOnFailure>0</SyncWorkflowLogOnFailure>
      <StateCode>0</StateCode><StatusCode>1</StatusCode>
      <RunAs>1</RunAs><IsTransacted>1</IsTransacted><IntroducedVersion>1.0</IntroducedVersion>
      <IsCustomizable>1</IsCustomizable><BusinessProcessType>0</BusinessProcessType>
      <PrimaryEntity>none</PrimaryEntity>
      <LocalizedNames><LocalizedName languagecode="3082" description="{nombre}" /></LocalizedNames>
    </Workflow>
  </Workflows>
  <FieldSecurityProfiles></FieldSecurityProfiles>
  <Templates /><EntityMaps /><EntityRelationships /><OrganizationSettings />
  <optionsets /><CustomControls /><EntityDataProviders />
  <connectionreferences />
  <Languages><Language>3082</Language></Languages>
</ImportExportXml>
"""
    content_types = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/octet-stream" />'
        '<Default Extension="json" ContentType="application/octet-stream" /></Types>'
    )
    archivos = {
        "[Content_Types].xml": content_types,
        "solution.xml": solution_xml,
        "customizations.xml": customizations,
        wf_file: wf_json,
    }
    for k, v in ENV_VARS.items():
        if k.startswith("_"):
            continue
        archivos[f"environmentvariabledefinitions/{k}/environmentvariabledefinition.xml"] = f"""<?xml version="1.0" encoding="utf-8"?>
<environmentvariabledefinition schemaname="{k}">
  <defaultvalue>{_xml_esc(v['default'])}</defaultvalue>
  <displayname default="{_xml_esc(v['display'])}"><label description="{_xml_esc(v['display'])}" languagecode="3082" /></displayname>
  <introducedversion>1.0</introducedversion>
  <iscustomizable>1</iscustomizable>
  <isrequired>1</isrequired>
  <secretstore>0</secretstore>
  <type>100000000</type>
</environmentvariabledefinition>
"""
    return archivos


# ---------------------------------------------------------------- zip
def escribir_zip(ruta, archivos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre in sorted(archivos):
            cont = archivos[nombre]
            if not isinstance(cont, str):
                cont = json.dumps(cont, indent=2, ensure_ascii=False)
            zi = zipfile.ZipInfo(nombre, date_time=_ZIP_FECHA)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, cont.encode("utf-8"))
    return ruta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist"))
    a = ap.parse_args(argv)
    v = a.version
    r1 = escribir_zip(os.path.join(a.out, f"{FLOW['id']}_v{v}_legacy.zip"), construir_legacy(FLOW, v))
    r2 = escribir_zip(os.path.join(a.out, f"{FLOW['id']}_v{v}_solution.zip"), construir_solution(FLOW, v))
    print(r1)
    print(r2)


if __name__ == "__main__":
    main()
