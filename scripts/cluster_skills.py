"""
Deterministic skill clustering — no LLM.
Runs once, writes clusters directly to the skill_clusters DB table.
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.skill_taxonomy import get_taxonomy
from backend.db import get_conn

# ── Cluster definitions ───────────────────────────────────────────────────────
# Each cluster: (name, domain_tags, [keyword fragments — case-insensitive substring match])
# A skill lands in the FIRST cluster whose any keyword matches.
# Unmatched skills go to "Other".

CLUSTERS = [
    ("Programming Languages", ["software", "embedded"], [
        "python", "java", "javascript", "typescript", "c++", "c/c++", "c#", "c/c#",
        "kotlin", "scala", "rust", "go ", "golang", "ruby", "swift", "ada", "perl",
        "bash", "vba", "matlab", "r ", "fortran", "cobol", "assembler", "php",
        "c++17", "c++20", "html", "css", "sql", "pl/sql", "abap", "pspice",
    ]),
    ("Embedded & RTOS", ["embedded", "automotive", "hardware"], [
        "bare-metal", "firmware", "bootloader", "rtos", "freertos", "vxworks",
        "embedded linux", "embedded system", "embedded-system", "embedded design",
        "mikrocontroller", "microcontroller", "systemd", "dbus", "yocto", "bitbake",
        "arm ", "arm cortex", "aurix", "tricore", "cortex-m",
        "echtzeitbetriebssystem", "leistungselektronik", "embedded c",
        "embedded software", "bsp", "hal", "hardware abstraction",
    ]),
    ("Automotive Protocols & Standards", ["automotive", "embedded", "networking"], [
        "can bus", "can 2.0", "canopen", "flexray", "lin ", "uds", "iso 14229",
        "iso 15765", "sae j1939", "autosar", "autosar mcal", "autosar bsw",
        "autosar rte", "autosar asw", "xcp", "obd", "doip", "someip",
        "automotive ethernet", "most ", "a2l", "autosar mcal",
    ]),
    ("Communication Protocols", ["networking", "embedded"], [
        "ethernet", "tcp/ip", "udp", "multicast", "icmp", "igmp",
        "i2c", "spi", "uart", "rs232", "rs485", "modbus", "profibus", "profinet",
        "rest", "soap", "mqtt", "opc-ua", "opc ua", "grpc", "websocket",
        "bluetooth", "wifi", "wireless", "zigbee", "lora", "uwb",
        "ble ", "nfc ", "5g ", "lte ", "can ", "flexray",
    ]),
    ("Safety & Functional Safety", ["safety", "automotive", "embedded"], [
        "iso 26262", "iec 61508", "iec 61511", "iec 62061", "iec62682", "iec61511",
        "aspice", "sil ", "asil", "fmea", "fta ", "fha ", "hara",
        "mil-std 882", "do-178", "do-254", "do-160", "arp4754",
        "safety engineering", "functional safety", "sicherheitsbewertung",
        "sicherheitskritisch", "maschinensicherheit",
    ]),
    ("Security & Cybersecurity", ["security", "software"], [
        "cyber", "cybersecurity", "iso 27001", "iec 62443", "iso 21434",
        "common criteria", "bsi it-grundschutz", "oauth2", "openid connect",
        "it-security", "it security", "security", "penetration", "soc ",
        "encryption", "cryptograph", "nis-2", "data act", "cyber resilience",
        "radio equipment directive", "software security", "it sicherheit",
    ]),
    ("Aerospace & Defence", ["aerospace", "safety", "hardware"], [
        "avionics", "aerospace", "eurofighter", "airbus", "do-160", "do-178",
        "mil-std", "easa", "en 9100", "comint", "electronic warfare",
        "radar", "sigint", "eo/ir", "hf-verstärker", "hf-messtechnik",
        "satellite", "spacecraft", "earth observation", "flight control",
        "navigation system", "combat", "defence", "military", "militär",
        "luft- und raumfahrt", "airbus helicopters", "fighter aircraft",
        "electromagnetic hazard", "hirf", "ils ", "lora ", "logistik support",
        "maintenance task", "spare parts", "type certification",
        "luftfahrt", "emar", "cfrp", "quantum",
    ]),
    ("Cloud & DevOps", ["cloud", "tooling", "software"], [
        "docker", "kubernetes", "helm", "aws", "azure", "gcp", "cloud",
        "ci/cd", "devops", "infrastructure as code", "terraform", "ansible",
        "jenkins", "gitlab ci", "github actions", "ecs ", "rds ", "s3 ",
        "lambda ", "sqs ", "event hubs", "adls", "fabric ", "emr ",
        "azure devops", "gitlab", "containeriz",
    ]),
    ("Databases", ["software", "data"], [
        "sql", "mysql", "postgresql", "oracle", "mongodb", "elasticsearch",
        "redis ", "cassandra", "nosql", "database", "datenbank", "pl/sql",
        "jpa ", "hibernate", "flyway", "delta lake", "data warehouse",
        "ms sql", "spark ", "airflow", "kafka",
    ]),
    ("Web & Backend Frameworks", ["software"], [
        "spring boot", "spring security", "jakarta ee", "fastapi", "flask",
        "django", "express", ".net ", "asp.net", "microservice", "rest-schnittstelle",
        "openapi", "angular", "react ", "vue ", "node.js", "streamlit",
        "oauth2", "jakarta", "osgi", "eclipse rcp",
    ]),
    ("AI & Data Science", ["data", "software", "cloud"], [
        "machine learning", "deep learning", "llm", "generative ai", "rag ",
        "llmops", "artificial intelligence", "künstliche intelligenz",
        "sensor fusion", "signal processing", "pandas", "numpy",
        "scikit", "tensorflow", "pytorch", "data analysis", "data science",
        "big data", "internet of things", "iot ", "power bi", "powerbi",
        "business intelligence", "analytics", "forecasting", "ai ",
    ]),
    ("Build, Test & QA Tools", ["tooling", "testing", "software"], [
        "junit", "mockito", "cucumber", "tdd", "robot framework", "catch2",
        "google test", "vector cast", "unit test", "modultests",
        "pytest", "selenium", "teststand", "labview", "labwindows",
        "performance-test", "automatisierte test", "sil test",
        "quality center", "polarion", "jama", "codebeamer",
    ]),
    ("Version Control & Build Systems", ["tooling", "software"], [
        "git ", "github", "gitlab", "svn ", "mercurial",
        "maven", "gradle", "cmake", "conan ", "make ",
        "version control", "versionskontrolle", "build system",
    ]),
    ("Project & Requirements Management", ["methodology", "tooling"], [
        "jira", "confluence", "doors", "doors classic", "cameo",
        "rhapsody", "polarion", "codebeamer", "alm-tools", "powerppm",
        "jama ", "microsoft project", "ms project", "primavera",
        "project management", "projektmanagement", "pmp", "prince2",
        "ipma", "safe ", "scrum", "kanban", "agile", "v-modell",
        "aspice", "mbse", "systems engineering", "sysml", "uml ",
    ]),
    ("ERP & Enterprise Systems", ["tooling", "software"], [
        "sap ", "erp", "sap ewm", "sap sd", "sap mm", "sap ariba",
        "sap gts", "sap plm", "sap erp", "sap 800", "sap-mm",
        "abap", "salesforce", "crm ", "microsoft 365", "sharepoint",
        "ms office", "microsoft office", "excel", "word ", "powerpoint",
        "power apps", "power automate", "dataverse", "microsoft power platform",
    ]),
    ("Simulation & Modelling", ["software", "hardware", "embedded"], [
        "matlab", "simulink", "ansys", "comsol", "femm", "pspice",
        "finite element", "computational fluid", "dspace", "dspace-toolchain",
        "modelica", "scilab", "simulink coder", "plecs ", "inca ",
        "simulation", "digital twin",
    ]),
    ("Electronics & PCB Design", ["hardware", "embedded"], [
        "allegro", "altium", "eplan", "zuken", "e-cad", "ecad",
        "pcb", "schaltungsdesign", "schaltungslayout", "layout-tool",
        "pcb-design", "schematic", "schaltplan",
        "oscilloscope", "oszilloskop", "spectrum analyser", "spektrumanalysator",
        "soldering", "electronic assembly", "elektrische baugruppe",
    ]),
    ("Power & Energy Systems", ["hardware", "embedded", "automotive"], [
        "power electronics", "leistungselektronik", "frequency converter",
        "drive technology", "motor control", "battery energy storage",
        "power transformer", "switchgear", "circuit breaker",
        "high voltage", "medium voltage", "low voltage", "hvdc",
        "grid code", "load flow", "short circuit", "protection coordination",
        "harmonic", "voltage regulation", "substation", "power-to-x",
        "heat pump", "biomass", "hydrogen", "renewable",
        "etap", "powerfacto", "knx", "hvac", "bms ",
        "energiemanagement", "niederspannung",
    ]),
    ("Industrial Automation & Robotics", ["embedded", "hardware", "automotive"], [
        "plc ", "sps ", "siemens s7", "tia portal", "siemens sinumerik",
        "siemens simatic", "hmi ", "scada", "abb robotics", "kuka",
        "kuka krl", "robot", "robotik", "cnc", "6-achs",
        "industrial automation", "industrieautomation", "flexarc",
        "automationsanlage", "scara", "laser", "bildverarbeitung",
    ]),
    ("Mechanical & CAD", ["hardware", "mechanical"], [
        "solidworks", "autocad", "creo ", "siemens nx", "catia",
        "cad ", "3d-druck", "additive fertigung", "mechanical design",
        "mechanisches design", "finite element", "cfrp", "hydraulik",
        "pneumatik", "regelungstechnik", "maschinenbau",
    ]),
    ("Methodologies & Processes", ["methodology"], [
        "scrum", "kanban", "agile", "safe ", "lean ", "six sigma",
        "v-modell", "aspice", "apqp", "fmea", "8d ", "kaizen",
        "ci/cd", "tdd", "devops", "continuous improvement",
        "prince2", "pmp", "ipma", "itil", "safe ",
    ]),
    ("Software Engineering Practices", ["software"], [
        "software architect", "softwarearchitektur", "software-architektur",
        "design pattern", "software-design", "solid-prinzip", "solid prinzip",
        "object oriented", "objektorientiert", "oop ", "clean code",
        "code review", "codequalit", "pair-programming", "refactoring",
        "softwareentwicklung", "softwareengineering", "software engineering",
        "software craftsmanship", "software-engineering",
        "entwicklungsprozess", "release", "debugging", "testing",
        "unit-test", "unit test", "modultests", "automatisierte test",
        "scalierbar", "skalierbar", "nebenläufigkeit", "threading",
        "coroutine", "concurrenc", "performanceoptimierung",
        "dokumentation", "doxygen", "technical specification",
        "verification", "validation", "anforderungsmanagement",
        "requirements", "traceability",
    ]),
    ("Networking & IT Systems", ["networking", "software"], [
        "linux", "unix", "windows server", "network", "netzwerk",
        "tcp", "ip ", "firewall", "vpn ", "dns ", "dhcp",
        "system- & netzwerk", "it-system", "infrastructure",
        "infrastrukturmanagement", "podman", "apparmor", "selinux",
        "systemintegration", "visual studio", "android",
        "web development", "webentwicklung",
    ]),
    ("Quality Management", ["methodology", "software"], [
        "qualität", "qualitäts", "quality management", "quality assurance",
        "qualitätssicherung", "qualitätskontrolle", "qm ", "qa ",
        "iso 9001", "iso 13485", "iatf", "audit", "normen", "norm ",
        "vde ", "din ", "certification", "zertifizierung",
        "process control", "process optimiz", "prozessoptimierung",
        "konfigurationsmanagement", "änderungsmanagement",
        "versions- und änderung",
    ]),
    ("Supply Chain & Logistics", ["tooling"], [
        "supply chain", "logistics", "logistik", "inventory",
        "warehouse", "procurement", "einkauf", "beschaffung",
        "incoterms", "lead time", "customs", "import/export",
        "demand planning", "material plan", "lager",
    ]),
    ("Electrical & Electronics Engineering", ["hardware", "embedded"], [
        "elektrotechnik", "electrical engineering", "electronics engineering",
        "elektronik", "elektrik", "elektroniker", "elektriker",
        "schaltkreis", "circuit", "hardwareentwicklung", "hardware design",
        "hardware prototyping", "e/e-architektur", "messtechnik",
        "mess- und prüf", "electromagnetic", "emc ", "emi ",
        "elektromagnet", "esd-schutz", "hochfrequenz", "hf-",
        "signalverarbeitung", "signal processing", "sensor",
        "sensorik", "optic", "optik", "kamera", "mechanical actuation",
        "actuator", "relay", "magnete", "magnetic",
    ]),
    ("Systems Engineering", ["methodology", "hardware", "software"], [
        "systems engineering", "system engineering", "systemintegration",
        "system designer", "mbse", "sysml", "uml", "e/e-architektur",
        "subsystem", "integrated logistics support", "ils ",
        "maintenance program", "logistik support",
    ]),
    ("Languages", ["methodology"], [
        "deutsch", "englisch", "german", "english", "french", "spanish",
        "italian", "czech", "slovak", "hungarian", "polish", "angielski",
        "język angielski", "deutschkenntnisse", "englischkenntnisse",
        "b1 ", "b2 ", "c1 ", "c2 ",
    ]),
]

# ── Cluster assignment ────────────────────────────────────────────────────────

def assign_clusters(skills: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {name: [] for name, _, _ in CLUSTERS}
    result["Other"] = []

    for skill in skills:
        skill_lower = skill.lower()
        placed = False
        for name, _, keywords in CLUSTERS:
            if any(kw in skill_lower for kw in keywords):
                result[name].append(skill)
                placed = True
                break
        if not placed:
            result["Other"].append(skill)

    return result


def main():
    skills = get_taxonomy()
    print(f"Clustering {len(skills)} skills…")

    clusters = assign_clusters(skills)

    for name, skills_in in clusters.items():
        print(f"  {name}: {len(skills_in)}")

    print(f"\nTotal clustered: {sum(len(v) for v in clusters.values())}")
    print(f"Other (unmatched): {len(clusters['Other'])}")
    if clusters["Other"]:
        print("  Sample Other:", clusters["Other"][:20])

    # Write to DB
    with get_conn() as conn:
        conn.execute("DELETE FROM skill_clusters")
        for (name, domain_tags, _), skills_in in zip(
            [(n, d, k) for n, d, k in CLUSTERS] + [("Other", [], [])],
            [clusters[n] for n, _, _ in CLUSTERS] + [clusters["Other"]]
        ):
            if not skills_in:
                continue
            conn.execute(
                "INSERT INTO skill_clusters (name, skills_json, domain_tags_json, skill_count) VALUES (?,?,?,?)",
                (name, json.dumps(skills_in, ensure_ascii=False),
                 json.dumps(domain_tags, ensure_ascii=False), len(skills_in))
            )

    print("\nDone — clusters written to DB.")


if __name__ == "__main__":
    main()
