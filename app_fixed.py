#!/usr/bin/env python3
"""
Legal Assistant Web Service (Fixed Version)

This Flask application provides a web interface and API endpoints for the
DataJud Legal Assistant. It allows users to interact with the assistant
through a web browser or programmatically through API calls.

This application is designed to be deployed on Render or similar cloud services.

Usage:
    python app_fixed.py

Environment Variables:
    OPENAI_API_KEY: Your OpenAI API key
    PORT: Port to run the server on (default: 8080)
    DATAJUD_API_KEY: (Optional) Override the default DataJud API key
"""

import os
import json
import logging
import re
import time
import traceback
from typing import Dict, List, Any, Optional, Union, Tuple
from threading import Lock
from datetime import datetime

# Try to import dotenv for API key management
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# Import Flask
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS

# Import OpenAI
import openai
from openai import OpenAIError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("legal_assistant.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for API endpoints
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

# Get OpenAI API key from environment variable
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning(
        "OPENAI_API_KEY environment variable not set. "
        "The application will not work without a valid API key."
    )

# Initialize OpenAI client with timeout
client = openai.OpenAI(
    api_key=OPENAI_API_KEY,
    timeout=60.0  # 60 second timeout for API calls
)

# DataJud API Configuration
API_BASE_URL = "https://api-publica.datajud.cnj.jus.br"
API_KEY = os.getenv("DATAJUD_API_KEY", "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==")
HEADERS = {
    "Authorization": f"ApiKey {API_KEY}",
    "Content-Type": "application/json"
}

# Define court endpoints
COURTS = {
    "TJSP": f"{API_BASE_URL}/api_publica_tjsp/_search",
    "STJ": f"{API_BASE_URL}/api_publica_stj/_search",
    "TRF1": f"{API_BASE_URL}/api_publica_trf1/_search",
    "TRF2": f"{API_BASE_URL}/api_publica_trf2/_search",
    "TRF3": f"{API_BASE_URL}/api_publica_trf3/_search",
    "TRF4": f"{API_BASE_URL}/api_publica_trf4/_search",
    "TRF5": f"{API_BASE_URL}/api_publica_trf5/_search",
    "TRF6": f"{API_BASE_URL}/api_publica_trf6/_search",
}

# Common movement codes and their meanings
# Updated based on API exploration results
MOVEMENT_CODES = {
    26: "Distribuição",
    51: "Conclusão",
    60: "Cumprimento",
    92: "Expedição",
    123: "Publicação",
    132: "Recebimento",
    246: "Definitivo",
    493: "Arquivamento Provisório",
    581: "Documento",
    970: "Audiência Realizada",
    982: "Migração de Sistema",
    1051: "Penhora",
    11010: "Ato Ordinatório Praticado",
    11376: "Apensamento",
    11383: "Ato ordinatório",
    12263: "Intimação Eletrônica Expedida/Certificada",
    14732: "Conversão de Autos Físicos em Eletrônicos",
    
    # Additional codes from previous examples
    11009: "Despacho",
    11022: "Decisão",
    193: "Julgamento",
    220: "Baixa Definitiva",
    848: "Arquivamento Definitivo",
    11385: "Arquivamento",
    133: "Remessa",
    11382: "Bloqueio/penhora on line",
    245: "Provisório"
}

# Common class codes and their meanings
# Updated based on API exploration results
CLASS_CODES = {
    436: "Procedimento do Juizado Especial Cível",
    1116: "Execução Fiscal",
    # Add more class codes as they are discovered
}

# Tool definitions for OpenAI function calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_process_by_number",
            "description": "Busca um processo judicial pelo seu número em um tribunal específico ou em múltiplos tribunais",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_number": {
                        "type": "string",
                        "description": "Número do processo judicial (formato CNJ sem pontuação)"
                    },
                    "court": {
                        "type": "string",
                        "description": "Sigla do tribunal (TJSP, STJ, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6). Se não especificado, busca em todos os tribunais disponíveis.",
                        "enum": list(COURTS.keys()) + ["TODOS"]
                    }
                },
                "required": ["process_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_status",
            "description": "Obtém o status atual de um processo judicial",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_number": {
                        "type": "string",
                        "description": "Número do processo judicial (formato CNJ sem pontuação)"
                    },
                    "court": {
                        "type": "string",
                        "description": "Sigla do tribunal (TJSP, STJ, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6). Se não especificado, busca em todos os tribunais disponíveis.",
                        "enum": list(COURTS.keys()) + ["TODOS"]
                    }
                },
                "required": ["process_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_class_and_judge",
            "description": "Busca processos por classe processual e órgão julgador",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_code": {
                        "type": "integer",
                        "description": "Código da classe processual (ex: 1116 para Execução Fiscal, 436 para Procedimento do Juizado Especial Cível)"
                    },
                    "judge_code": {
                        "type": "integer",
                        "description": "Código do órgão julgador"
                    },
                    "court": {
                        "type": "string",
                        "description": "Sigla do tribunal (TJSP, STJ, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6)",
                        "enum": list(COURTS.keys())
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número máximo de resultados (1-100)",
                        "default": 10
                    }
                },
                "required": ["class_code", "judge_code", "court"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_movements",
            "description": "Obtém os movimentos processuais de um processo judicial",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_number": {
                        "type": "string",
                        "description": "Número do processo judicial (formato CNJ sem pontuação)"
                    },
                    "court": {
                        "type": "string",
                        "description": "Sigla do tribunal (TJSP, STJ, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6)",
                        "enum": list(COURTS.keys())
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número máximo de movimentos a retornar",
                        "default": 10
                    }
                },
                "required": ["process_number", "court"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_details",
            "description": "Obtém detalhes completos de um processo judicial",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_number": {
                        "type": "string",
                        "description": "Número do processo judicial (formato CNJ sem pontuação)"
                    },
                    "court": {
                        "type": "string",
                        "description": "Sigla do tribunal (TJSP, STJ, TRF1, TRF2, TRF3, TRF4, TRF5, TRF6)",
                        "enum": list(COURTS.keys())
                    }
                },
                "required": ["process_number", "court"]
            }
        }
    }
]

# System message for the assistant
SYSTEM_MESSAGE = """
Você é um assistente jurídico especializado em consultar informações processuais do sistema judiciário brasileiro.
Você tem acesso a ferramentas que permitem consultar o DataJud, a base de dados do Conselho Nacional de Justiça (CNJ).

Você pode:
1. Buscar processos pelo número (search_process_by_number)
2. Verificar o status atual de processos (get_process_status)
3. Buscar processos por classe e órgão julgador (search_by_class_and_judge)
4. Obter movimentos processuais (get_process_movements)
5. Obter detalhes completos de processos (get_process_details)

Quando o usuário fizer uma pergunta sobre um processo judicial, você deve:
1. Identificar qual ferramenta usar com base na pergunta
2. Extrair as informações necessárias da pergunta (número do processo, tribunal, etc.)
3. Usar a ferramenta apropriada para consultar o DataJud
4. Apresentar as informações de forma clara e organizada

Você atende apenas aos seguintes tribunais:
- Tribunal de Justiça de São Paulo (TJSP)
- Tribunal Superior de Justiça (STJ)
- Tribunais Regionais Federais (TRF1, TRF2, TRF3, TRF4, TRF5, TRF6)

Dicas importantes:
- Se o usuário não especificar um tribunal, você deve tentar buscar em todos os tribunais disponíveis.
- Se o usuário mencionar um processo sem o número completo, peça gentilmente que forneça o número completo.
- Explique sempre o significado dos códigos de movimento e classe processual.
- Sempre formate datas no padrão brasileiro (DD/MM/AAAA).
- Seja educado, profissional e objetivo nas suas respostas.

Responda sempre em português e de forma educada e profissional.
"""

# Dictionary to store conversation histories by session ID
conversation_histories = {}
conversation_lock = Lock()

# Custom JSON encoder to handle non-serializable objects
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def safe_json_dumps(obj):
    """
    Safely convert an object to a JSON string, handling non-serializable objects.
    
    Args:
        obj: The object to convert
        
    Returns:
        JSON string representation of the object
    """
    try:
        return json.dumps(obj, ensure_ascii=False, cls=CustomJSONEncoder)
    except (TypeError, ValueError, OverflowError) as e:
        logger.error(f"JSON serialization error: {str(e)}")
        # Try to create a simplified version of the object
        if isinstance(obj, dict):
            simplified = {}
            for k, v in obj.items():
                try:
                    # Test if the value is serializable
                    json.dumps({k: v}, ensure_ascii=False)
                    simplified[k] = v
                except (TypeError, ValueError, OverflowError):
                    simplified[k] = str(v)
            return json.dumps(simplified, ensure_ascii=False)
        elif isinstance(obj, list):
            return json.dumps([str(item) for item in obj], ensure_ascii=False)
        else:
            return json.dumps(str(obj), ensure_ascii=False)


def search_process_by_number(process_number: str, court: Optional[str] = None) -> Dict:
    """
    Busca um processo pelo seu número em um tribunal específico ou em múltiplos tribunais.
    
    Args:
        process_number: Número do processo judicial (formato CNJ sem pontuação)
        court: Sigla do tribunal. Se for "TODOS" ou None, busca em todos os tribunais
        
    Returns:
        Dicionário com os resultados da busca
    """
    # Format process number (remove any special characters)
    process_number = ''.join(filter(str.isdigit, process_number))
    
    results = {
        "processo_encontrado": False,
        "tribunal": None,
        "dados_processo": None,
        "mensagem": "Processo não encontrado em nenhum tribunal."
    }
    
    # Determine which courts to search
    courts_to_search = []
    if court and court != "TODOS":
        if court not in COURTS:
            return {
                "processo_encontrado": False,
                "mensagem": f"Tribunal {court} não suportado. Tribunais suportados: {list(COURTS.keys())}"
            }
        courts_to_search = [court]
    else:
        courts_to_search = list(COURTS.keys())
    
    # Search in each court
    for court_name in courts_to_search:
        endpoint = COURTS[court_name]
        
        query = {
            "query": {
                "match": {
                    "numeroProcesso": process_number
                }
            }
        }
        
        try:
            import requests
            response = requests.post(
                endpoint, 
                headers=HEADERS, 
                data=json.dumps(query),
                timeout=10  # 10 second timeout
            )
            response.raise_for_status()
            data = response.json()
            
            hits = data.get("hits", {}).get("hits", [])
            if hits:
                # Process found
                process_data = hits[0].get("_source", {})
                results = {
                    "processo_encontrado": True,
                    "tribunal": court_name,
                    "dados_processo": process_data,
                    "mensagem": f"Processo encontrado no tribunal {court_name}."
                }
                # Once found, no need to search in other courts
                break
        
        except requests.exceptions.Timeout:
            logger.error(f"Timeout ao consultar {court_name} para o processo {process_number}")
            results["mensagem"] = f"Timeout ao consultar o tribunal {court_name}. Tente novamente mais tarde."
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao consultar {court_name} para o processo {process_number}: {e}")
            results["mensagem"] = f"Erro ao consultar o tribunal {court_name}: {str(e)}"
        except json.JSONDecodeError:
            logger.error(f"Erro ao decodificar resposta JSON do tribunal {court_name}")
            results["mensagem"] = f"Erro ao processar resposta do tribunal {court_name}. Formato inválido."
        except Exception as e:
            logger.error(f"Erro inesperado ao consultar {court_name}: {e}")
            results["mensagem"] = f"Erro inesperado ao consultar o tribunal {court_name}: {str(e)}"
        
        # Avoid rate limiting
        time.sleep(0.5)
    
    return results


def get_process_status(process_number: str, court: Optional[str] = None) -> Dict:
    """
    Obtém o status atual de um processo judicial.
    
    Args:
        process_number: Número do processo judicial (formato CNJ sem pontuação)
        court: Sigla do tribunal. Se for "TODOS" ou None, busca em todos os tribunais
        
    Returns:
        Dicionário com informações sobre o status do processo
    """
    # First search for the process
    search_result = search_process_by_number(process_number, court)
    
    if not search_result["processo_encontrado"]:
        return {
            "status": "não_encontrado",
            "mensagem": search_result["mensagem"]
        }
    
    # Process found, extract status information
    process_data = search_result["dados_processo"]
    
    status_info = {
        "status": "encontrado",
        "numero_processo": process_data.get("numeroProcesso"),
        "tribunal": process_data.get("tribunal"),
        "data_ajuizamento": format_date(process_data.get("dataAjuizamento")),
        "classe": None,
        "orgao_julgador": None,
        "ultimo_movimento": None,
        "data_ultimo_movimento": None,
        "situacao_atual": "Em andamento",  # Default status
        "assuntos": []
    }
    
    # Extract class information
    if "classe" in process_data:
        class_info = process_data["classe"]
        class_code = class_info.get("codigo")
        status_info["classe"] = {
            "codigo": class_code,
            "nome": class_info.get("nome"),
            "descricao": CLASS_CODES.get(class_code, class_info.get("nome"))
        }
    
    # Extract judging body information
    if "orgaoJulgador" in process_data:
        judge_info = process_data["orgaoJulgador"]
        status_info["orgao_julgador"] = {
            "codigo": judge_info.get("codigo"),
            "nome": judge_info.get("nome"),
            "codigo_municipio": judge_info.get("codigoMunicipioIBGE")
        }
    
    # Extract subjects
    if "assuntos" in process_data:
        assuntos = process_data["assuntos"]
        if isinstance(assuntos, list):
            # Handle different possible structures
            if assuntos and isinstance(assuntos[0], list):
                # Format [[{code, name}], [{code, name}]]
                for assunto_group in assuntos:
                    if assunto_group and isinstance(assunto_group[0], dict):
                        status_info["assuntos"].append({
                            "codigo": assunto_group[0].get("codigo"),
                            "nome": assunto_group[0].get("nome")
                        })
            elif assuntos and isinstance(assuntos[0], dict):
                # Format [{code, name}, {code, name}]
                for assunto in assuntos:
                    status_info["assuntos"].append({
                        "codigo": assunto.get("codigo"),
                        "nome": assunto.get("nome")
                    })
    
    # Extract movements (most recent first)
    movements = process_data.get("movimentos", [])
    if movements:
        # Sort movements by date (most recent first)
        try:
            sorted_movements = sorted(
                movements, 
                key=lambda x: x.get("dataHora", ""), 
                reverse=True
            )
            
            # Get the most recent movement
            if sorted_movements:
                last_movement = sorted_movements[0]
                movement_code = last_movement.get("codigo")
                movement_name = last_movement.get("nome")
                
                status_info["ultimo_movimento"] = {
                    "codigo": movement_code,
                    "nome": movement_name,
                    "descricao": MOVEMENT_CODES.get(movement_code, movement_name)
                }
                status_info["data_ultimo_movimento"] = format_date(last_movement.get("dataHora"))
                
                # Determine current situation based on last movement
                if movement_code in [220, 848, 11385]:  # Baixa/Arquivamento
                    status_info["situacao_atual"] = "Arquivado/Baixado"
                elif movement_code == 246:  # Definitivo
                    status_info["situacao_atual"] = "Arquivado Definitivamente"
                elif movement_code == 493:  # Arquivamento Provisório
                    status_info["situacao_atual"] = "Arquivado Provisoriamente"
                elif movement_code == 193:  # Julgamento
                    status_info["situacao_atual"] = "Julgado"
                elif movement_code in [11009, 11022]:  # Despacho/Decisão
                    status_info["situacao_atual"] = "Em andamento (com despacho/decisão recente)"
                elif movement_code == 51:  # Concluso
                    status_info["situacao_atual"] = "Concluso para despacho/decisão"
                elif movement_code == 11383:  # Ato ordinatório
                    status_info["situacao_atual"] = "Em andamento (com ato ordinatório recente)"
                elif movement_code == 12263:  # Intimação Eletrônica
                    status_info["situacao_atual"] = "Em andamento (com intimação recente)"
        except Exception as e:
            logger.error(f"Erro ao processar movimentos: {str(e)}")
            status_info["situacao_atual"] = "Em andamento (erro ao processar movimentos)"
    
    # Format response in Portuguese
    response = {
        "status": "encontrado",
        "numero_processo": status_info["numero_processo"],
        "tribunal": status_info["tribunal"],
        "data_ajuizamento": status_info["data_ajuizamento"],
        "situacao_atual": status_info["situacao_atual"],
        "ultimo_movimento": status_info["ultimo_movimento"]["descricao"] if status_info["ultimo_movimento"] else None,
        "data_ultimo_movimento": status_info["data_ultimo_movimento"],
        "classe_processual": status_info["classe"]["descricao"] if status_info["classe"] else None,
        "orgao_julgador": status_info["orgao_julgador"]["nome"] if status_info["orgao_julgador"] else None,
        "assuntos": [assunto["nome"] for assunto in status_info["assuntos"]],
        "detalhes_completos": status_info
    }
    
    return response


def search_by_class_and_judge(class_code: int, judge_code: int, court: str, limit: int = 10) -> Dict:
    """
    Busca processos por classe processual e órgão julgador.
    
    Args:
        class_code: Código da classe processual
        judge_code: Código do órgão julgador
        court: Sigla do tribunal
        limit: Número máximo de resultados (1-100)
        
    Returns:
        Dicionário com os resultados da busca
    """
    if court not in COURTS:
        return {
            "sucesso": False,
            "mensagem": f"Tribunal {court} não suportado. Tribunais suportados: {list(COURTS.keys())}"
        }
    
    # Limit the number of results
    limit = min(max(1, limit), 100)
    
    endpoint = COURTS[court]
    
    query = {
        "size": limit,
        "query": {
            "bool": {
                "must": [
                    {"match": {"classe.codigo": class_code}},
                    {"match": {"orgaoJulgador.codigo": judge_code}}
                ]
            }
        },
        "sort": [
            {
                "@timestamp": {
                    "order": "asc"
                }
            }
        ]
    }
    
    try:
        import requests
        response = requests.post(
            endpoint, 
            headers=HEADERS, 
            data=json.dumps(query),
            timeout=15  # 15 second timeout for larger queries
        )
        response.raise_for_status()
        data = response.json()
        
        hits = data.get("hits", {}).get("hits", [])
        total_hits = data.get("hits", {}).get("total", {})
        total_value = 0
        
        # Handle different response formats for total hits
        if isinstance(total_hits, dict):
            total_value = total_hits.get("value", 0)
            relation = total_hits.get("relation", "eq")
            if relation == "gte":
                total_message = f"Mais de {total_value} processos encontrados"
            else:
                total_message = f"{total_value} processos encontrados"
        else:
            total_value = total_hits
            total_message = f"{total_value} processos encontrados"
        
        results = {
            "sucesso": True,
            "total_encontrado": total_value,
            "total_mensagem": total_message,
            "processos": [],
            "mensagem": f"Busca realizada com sucesso no tribunal {court}.",
            "classe_descricao": CLASS_CODES.get(class_code, f"Classe {class_code}")
        }
        
        # If we have a lot of results, add pagination info
        if total_value > limit:
            last_sort = None
            if hits:
                last_hit = hits[-1]
                last_sort = last_hit.get("sort")
                
            if last_sort:
                results["paginacao"] = {
                    "tem_mais_resultados": True,
                    "tamanho_pagina": limit,
                    "search_after": last_sort,
                    "instrucoes": "Para ver a próxima página, use o valor de search_after em uma nova consulta"
                }
        
        for hit in hits:
            process_data = hit.get("_source", {})
            
            # Extract basic process information
            process_info = {
                "numero_processo": process_data.get("numeroProcesso"),
                "classe": {
                    "codigo": process_data.get("classe", {}).get("codigo"),
                    "nome": process_data.get("classe", {}).get("nome")
                },
                "orgao_julgador": {
                    "codigo": process_data.get("orgaoJulgador", {}).get("codigo"),
                    "nome": process_data.get("orgaoJulgador", {}).get("nome")
                },
                "data_ajuizamento": format_date(process_data.get("dataAjuizamento"))
            }
            
            # Add last movement if available
            movements = process_data.get("movimentos", [])
            if movements:
                try:
                    sorted_movements = sorted(
                        movements, 
                        key=lambda x: x.get("dataHora", ""), 
                        reverse=True
                    )
                    
                    if sorted_movements:
                        last_movement = sorted_movements[0]
                        movement_code = last_movement.get("codigo")
                        process_info["ultimo_movimento"] = {
                            "codigo": movement_code,
                            "nome": last_movement.get("nome"),
                            "descricao": MOVEMENT_CODES.get(movement_code, last_movement.get("nome")),
                            "data": format_date(last_movement.get("dataHora"))
                        }
                except Exception as e:
                    logger.error(f"Erro ao processar movimentos para processo {process_info['numero_processo']}: {str(e)}")
            
            results["processos"].append(process_info)
        
        return results
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao consultar {court} com critérios classe={class_code}, juiz={judge_code}")
        return {
            "sucesso": False,
            "mensagem": f"Timeout ao consultar o tribunal {court}. Tente novamente mais tarde."
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao consultar {court} com critérios classe={class_code}, juiz={judge_code}: {e}")
        return {
            "sucesso": False,
            "mensagem": f"Erro ao consultar o tribunal {court}: {str(e)}"
        }
    except json.JSONDecodeError:
        logger.error(f"Erro ao decodificar resposta JSON do tribunal {court}")
        return {
            "sucesso": False,
            "mensagem": f"Erro ao processar resposta do tribunal {court}. Formato inválido."
        }
    except Exception as e:
        logger.error(f"Erro inesperado ao consultar {court}: {e}")
        return {
            "sucesso": False,
            "mensagem": f"Erro inesperado ao consultar o tribunal {court}: {str(e)}"
        }


def get_process_movements(process_number: str, court: str, limit: int = 10) -> Dict:
    """
    Obtém os movimentos processuais de um processo judicial.
    
    Args:
        process_number: Número do processo judicial (formato CNJ sem pontuação)
        court: Sigla do tribunal
        limit: Número máximo de movimentos a retornar
        
    Returns:
        Dicionário com os movimentos processuais
    """
    # First search for the process
    search_result = search_process_by_number(process_number, court)
    
    if not search_result["processo_encontrado"]:
        return {
            "sucesso": False,
            "mensagem": search_result["mensagem"]
        }
    
    # Process found, extract movements
    process_data = search_result["dados_processo"]
    
    # Extract movements
    movements = process_data.get("movimentos", [])
    
    if not movements:
        return {
            "sucesso": True,
            "numero_processo": process_number,
            "tribunal": court,
            "total_movimentos": 0,
            "movimentos": [],
            "mensagem": "Processo encontrado, mas não há movimentos registrados."
        }
    
    # Sort movements by date (most recent first)
    try:
        sorted_movements = sorted(
            movements, 
            key=lambda x: x.get("dataHora", ""), 
            reverse=True
        )
        
        # Limit the number of movements
        limited_movements = sorted_movements[:limit]
        
        # Format movements
        formatted_movements = []
        for movement in limited_movements:
            movement_code = movement.get("codigo")
            movement_name = movement.get("nome")
            
            formatted_movement = {
                "codigo": movement_code,
                "nome": movement_name,
                "descricao": MOVEMENT_CODES.get(movement_code, movement_name),
                "data": format_date(movement.get("dataHora")),
                "complementos": []
            }
            
            # Extract complements
            complementos = movement.get("complementosTabelados", [])
            for complemento in complementos:
                formatted_movement["complementos"].append({
                    "codigo": complemento.get("codigo"),
                    "descricao": complemento.get("descricao"),
                    "valor": complemento.get("valor"),
                    "nome": complemento.get("nome")
                })
            
            formatted_movements.append(formatted_movement)
        
        # Add basic process info
        processo_info = {
            "classe": None,
            "orgao_julgador": None,
            "data_ajuizamento": format_date(process_data.get("dataAjuizamento"))
        }
        
        # Extract class information
        if "classe" in process_data:
            class_info = process_data["classe"]
            class_code = class_info.get("codigo")
            processo_info["classe"] = {
                "codigo": class_code,
                "nome": class_info.get("nome"),
                "descricao": CLASS_CODES.get(class_code, class_info.get("nome"))
            }
        
        # Extract judging body information
        if "orgaoJulgador" in process_data:
            judge_info = process_data["orgaoJulgador"]
            processo_info["orgao_julgador"] = {
                "codigo": judge_info.get("codigo"),
                "nome": judge_info.get("nome"),
                "codigo_municipio": judge_info.get("codigoMunicipioIBGE")
            }
        
        return {
            "sucesso": True,
            "numero_processo": process_number,
            "tribunal": court,
            "processo_info": processo_info,
            "total_movimentos": len(movements),
            "movimentos_retornados": len(formatted_movements),
            "movimentos": formatted_movements,
            "mensagem": f"Movimentos processuais encontrados para o processo {process_number} no tribunal {court}."
        }
    except Exception as e:
        logger.error(f"Erro ao processar movimentos para processo {process_number}: {str(e)}")
        return {
            "sucesso": False,
            "mensagem": f"Erro ao processar movimentos do processo: {str(e)}"
        }


def get_process_details(process_number: str, court: str) -> Dict:
    """
    Obtém detalhes completos de um processo judicial.
    
    Args:
        process_number: Número do processo judicial (formato CNJ sem pontuação)
        court: Sigla do tribunal
        
    Returns:
        Dicionário com detalhes completos do processo
    """
    # First search for the process
    search_result = search_process_by_number(process_number, court)
    
    if not search_result["processo_encontrado"]:
        return {
            "sucesso": False,
            "mensagem": search_result["mensagem"]
        }
    
    # Process found, format details
    process_data = search_result["dados_processo"]
    
    # Basic process information
    class_code = process_data.get("classe", {}).get("codigo")
    
    details = {
        "sucesso": True,
        "numero_processo": process_data.get("numeroProcesso"),
        "tribunal": process_data.get("tribunal"),
        "grau": process_data.get("grau"),
        "data_ajuizamento": format_date(process_data.get("dataAjuizamento")),
        "nivel_sigilo": process_data.get("nivelSigilo"),
        "formato": {
            "codigo": process_data.get("formato", {}).get("codigo"),
            "nome": process_data.get("formato", {}).get("nome")
        },
        "sistema": {
            "codigo": process_data.get("sistema", {}).get("codigo"),
            "nome": process_data.get("sistema", {}).get("nome")
        },
        "classe": {
            "codigo": class_code,
            "nome": process_data.get("classe", {}).get("nome"),
            "descricao": CLASS_CODES.get(class_code, process_data.get("classe", {}).get("nome"))
        },
        "orgao_julgador": {
            "codigo": process_data.get("orgaoJulgador", {}).get("codigo"),
            "nome": process_data.get("orgaoJulgador", {}).get("nome"),
            "codigo_municipio": process_data.get("orgaoJulgador", {}).get("codigoMunicipioIBGE")
        },
        "assuntos": [],
        "movimentos": [],
        "data_ultima_atualizacao": format_date(process_data.get("dataHoraUltimaAtualizacao")),
        "mensagem": f"Detalhes completos do processo {process_number} no tribunal {court}."
    }
    
    # Extract subjects
    if "assuntos" in process_data:
        assuntos = process_data["assuntos"]
        if isinstance(assuntos, list):
            # Handle different possible structures
            if assuntos and isinstance(assuntos[0], list):
                # Format [[{code, name}], [{code, name}]]
                for assunto_group in assuntos:
                    if assunto_group and isinstance(assunto_group[0], dict):
                        details["assuntos"].append({
                            "codigo": assunto_group[0].get("codigo"),
                            "nome": assunto_group[0].get("nome")
                        })
            elif assuntos and isinstance(assuntos[0], dict):
                # Format [{code, name}, {code, name}]
                for assunto in assuntos:
                    details["assuntos"].append({
                        "codigo": assunto.get("codigo"),
                        "nome": assunto.get("nome")
                    })
    
    # Extract movements
    movements = process_data.get("movimentos", [])
    if movements:
        try:
            # Sort movements by date (most recent first)
            sorted_movements = sorted(
                movements, 
                key=lambda x: x.get("dataHora", ""), 
                reverse=True
            )
            
            for movement in sorted_movements:
                movement_code = movement.get("codigo")
                movement_name = movement.get("nome")
                
                formatted_movement = {
                    "codigo": movement_code,
                    "nome": movement_name,
                    "descricao": MOVEMENT_CODES.get(movement_code, movement_name),
                    "data": format_date(movement.get("dataHora")),
                    "complementos": []
                }
                
                # Extract complements
                complementos = movement.get("complementosTabelados", [])
                for complemento in complementos:
                    formatted_movement["complementos"].append({
                        "codigo": complemento.get("codigo"),
                        "descricao": complemento.get("descricao"),
                        "valor": complemento.get("valor"),
                        "nome": complemento.get("nome")
                    })
                
                details["movimentos"].append(formatted_movement)
            
            # Determine current situation based on last movement
            if details["movimentos"]:
                last_movement = details["movimentos"][0]
                movement_code = last_movement.get("codigo")
                
                if movement_code in [220, 848, 11385]:  # Baixa/Arquivamento
                    details["situacao_atual"] = "Arquivado/Baixado"
                elif movement_code == 246:  # Definitivo
                    details["situacao_atual"] = "Arquivado Definitivamente"
                elif movement_code == 493:  # Arquivamento Provisório
                    details["situacao_atual"] = "Arquivado Provisoriamente"
                elif movement_code == 193:  # Julgamento
                    details["situacao_atual"] = "Julgado"
                elif movement_code in [11009, 11022]:  # Despacho/Decisão
                    details["situacao_atual"] = "Em andamento (com despacho/decisão recente)"
                elif movement_code == 51:  # Concluso
                    details["situacao_atual"] = "Concluso para despacho/decisão"
                elif movement_code == 11383:  # Ato ordinatório
                    details["situacao_atual"] = "Em andamento (com ato ordinatório recente)"
                elif movement_code == 12263:  # Intimação Eletrônica
                    details["situacao_atual"] = "Em andamento (com intimação recente)"
                else:
                    details["situacao_atual"] = "Em andamento"
            else:
                details["situacao_atual"] = "Sem movimentação"
        except Exception as e:
            logger.error(f"Erro ao processar movimentos para processo {process_number}: {str(e)}")
            details["situacao_atual"] = "Em andamento (erro ao processar movimentos)"
            details["erro_movimentos"] = str(e)
    else:
        details["situacao_atual"] = "Sem movimentação"
    
    return details


def format_date(date_str: Optional[str]) -> Optional[str]:
    """
    Format a date string to a more readable format in Portuguese.
    
    Args:
        date_str: ISO date string (e.g., "2022-09-06T12:03:20.257Z")
        
    Returns:
        Formatted date string in Portuguese (e.g., "06/09/2022 12:03:20")
    """
    if not date_str:
        return None
    
    try:
        # Parse ISO format
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        # Format for Portuguese locale
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        # Return original if parsing fails
        return date_str
    except Exception as e:
        logger.error(f"Erro ao formatar data '{date_str}': {str(e)}")
        return date_str


def extract_process_number(text: str) -> Optional[str]:
    """
    Extract a process number from text using regex patterns.
    
    Args:
        text: Input text that may contain a process number
        
    Returns:
        Extracted process number or None if not found
    """
    # Pattern for CNJ format with or without formatting
    # 0000000-00.0000.0.00.0000 or 00000000000000000000
    patterns = [
        r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}',  # Formatted
        r'\d{20}'  # Unformatted
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            # Return the first match, removing any formatting
            return ''.join(filter(str.isdigit, matches[0]))
    
    # Try to find partial numbers that might be process numbers
    partial_pattern = r'\d{7,20}'
    matches = re.findall(partial_pattern, text)
    if matches:
        for match in matches:
            # If it's not a year or other common number
            if len(match) >= 10 and not re.match(r'(19|20)\d{2}', match):
                return match
    
    return None


def extract_court_from_text(text: str) -> Optional[str]:
    """
    Extract court information from text.
    
    Args:
        text: Input text that may mention a court
        
    Returns:
        Court code or None if not found
    """
    text = text.upper()
    
    court_keywords = {
        "TJSP": ["TJSP", "TRIBUNAL DE JUSTIÇA DE SÃO PAULO", "JUSTIÇA DE SÃO PAULO", "TJ-SP", "TJ/SP"],
        "STJ": ["STJ", "TRIBUNAL SUPERIOR DE JUSTIÇA", "SUPERIOR DE JUSTIÇA", "SUPERIOR TRIBUNAL"],
        "TRF1": ["TRF1", "TRIBUNAL REGIONAL FEDERAL DA 1", "TRF DA 1", "TRF-1", "TRF 1ª REGIÃO"],
        "TRF2": ["TRF2", "TRIBUNAL REGIONAL FEDERAL DA 2", "TRF DA 2", "TRF-2", "TRF 2ª REGIÃO"],
        "TRF3": ["TRF3", "TRIBUNAL REGIONAL FEDERAL DA 3", "TRF DA 3", "TRF-3", "TRF 3ª REGIÃO"],
        "TRF4": ["TRF4", "TRIBUNAL REGIONAL FEDERAL DA 4", "TRF DA 4", "TRF-4", "TRF 4ª REGIÃO"],
        "TRF5": ["TRF5", "TRIBUNAL REGIONAL FEDERAL DA 5", "TRF DA 5", "TRF-5", "TRF 5ª REGIÃO"],
        "TRF6": ["TRF6", "TRIBUNAL REGIONAL FEDERAL DA 6", "TRF DA 6", "TRF-6", "TRF 6ª REGIÃO"]
    }
    
    for court, keywords in court_keywords.items():
        for keyword in keywords:
            if keyword in text:
                return court
    
    # Additional check for federal courts in general
    if any(kw in text for kw in ["FEDERAL", "JUSTIÇA FEDERAL", "JF"]):
        return "FEDERAL"  # Special marker for any federal court
    
    return None


def run_agent(query: str, session_id: str) -> str:
    """
    Run the legal assistant agent with a user query.
    
    Args:
        query: User's query text
        session_id: Unique session identifier
        
    Returns:
        Response text
    """
    with conversation_lock:
        # Get or initialize conversation history
        if session_id not in conversation_histories:
            conversation_histories[session_id] = [
                {"role": "system", "content": SYSTEM_MESSAGE}
            ]
        
        conversation_history = conversation_histories[session_id]
    
    # Add user query to conversation
    conversation_history.append({"role": "user", "content": query})
    
    try:
        # Create a completion with function calling
        logger.info(f"Calling OpenAI API for query: {query}")
        start_time = time.time()
        
        try:
            response = client.chat.completions.create(
                model="gpt-4-turbo-preview",  # or another model with function calling
                messages=conversation_history,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.1,
                timeout=30.0  # 30 second timeout for OpenAI API calls
            )
            
            logger.info(f"OpenAI API call completed in {time.time() - start_time:.2f} seconds")
        except openai.APITimeoutError:
            logger.error("OpenAI API timeout")
            return "Desculpe, o serviço está demorando muito para responder. Por favor, tente novamente mais tarde."
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {str(e)}")
            return f"Erro ao consultar a API do OpenAI: {str(e)}. Por favor, tente novamente mais tarde."
        
        # Get the response message
        response_message = response.choices[0].message
        
        # Add assistant's message to conversation history
        try:
            # Convert tool_calls to a serializable format if needed
            tool_calls_serializable = None
            if response_message.tool_calls:
                tool_calls_serializable = []
                for tool_call in response_message.tool_calls:
                    tool_calls_serializable.append({
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
            
            conversation_history.append({
                "role": "assistant",
                "content": response_message.content,
                "tool_calls": tool_calls_serializable
            })
        except Exception as e:
            logger.error(f"Error adding assistant message to history: {str(e)}")
            # Continue with a simplified version of the message
            conversation_history.append({
                "role": "assistant",
                "content": response_message.content or "Mensagem sem conteúdo"
            })
        
        # Check if the model wants to call a function
        if response_message.tool_calls:
            # Process each tool call
            for tool_call in response_message.tool_calls:
                # Get function name and arguments
                function_name = tool_call.function.name
                
                try:
                    function_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing function arguments: {str(e)}")
                    function_args = {}
                
                # Log the function call
                logger.info(f"Calling function {function_name} with args: {function_args}")
                
                # Call the appropriate function
                function_response = None
                
                try:
                    if function_name == "search_process_by_number":
                        function_response = search_process_by_number(
                            process_number=function_args.get("process_number"),
                            court=function_args.get("court")
                        )
                    
                    elif function_name == "get_process_status":
                        function_response = get_process_status(
                            process_number=function_args.get("process_number"),
                            court=function_args.get("court")
                        )
                    
                    elif function_name == "search_by_class_and_judge":
                        function_response = search_by_class_and_judge(
                            class_code=function_args.get("class_code"),
                            judge_code=function_args.get("judge_code"),
                            court=function_args.get("court"),
                            limit=function_args.get("limit", 10)
                        )
                    
                    elif function_name == "get_process_movements":
                        function_response = get_process_movements(
                            process_number=function_args.get("process_number"),
                            court=function_args.get("court"),
                            limit=function_args.get("limit", 10)
                        )
                    
                    elif function_name == "get_process_details":
                        function_response = get_process_details(
                            process_number=function_args.get("process_number"),
                            court=function_args.get("court")
                        )
                    else:
                        function_response = {"error": f"Função desconhecida: {function_name}"}
                
                except Exception as e:
                    logger.error(f"Error calling function {function_name}: {str(e)}")
                    logger.error(traceback.format_exc())
                    function_response = {"error": f"Erro ao executar {function_name}: {str(e)}"}
                
                # Add function response to conversation
                try:
                    # Use safe_json_dumps to handle non-serializable objects
                    json_response = safe_json_dumps(function_response)
                    
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": json_response
                    })
                except Exception as e:
                    logger.error(f"Error adding function response to history: {str(e)}")
                    # Add a simplified error response
                    conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": json.dumps({"error": f"Erro ao processar resposta: {str(e)}"})
                    })
            
            # Get a new response from the model with the function response
            try:
                logger.info("Calling OpenAI API for final response")
                start_time = time.time()
                
                second_response = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=conversation_history,
                    temperature=0.1,
                    timeout=30.0  # 30 second timeout
                )
                
                logger.info(f"Final OpenAI API call completed in {time.time() - start_time:.2f} seconds")
                
                # Add the final response to conversation history
                second_message = second_response.choices[0].message
                conversation_history.append({
                    "role": "assistant",
                    "content": second_message.content
                })
                
                with conversation_lock:
                    # Update the conversation history in the shared dictionary
                    conversation_histories[session_id] = conversation_history
                
                return second_message.content
            
            except openai.APITimeoutError:
                logger.error("OpenAI API timeout for final response")
                error_message = "Desculpe, o serviço está demorando muito para processar sua consulta. Por favor, tente novamente mais tarde."
                conversation_history.append({
                    "role": "assistant",
                    "content": error_message
                })
                
                with conversation_lock:
                    # Update the conversation history in the shared dictionary
                    conversation_histories[session_id] = conversation_history
                
                return error_message
            
            except OpenAIError as e:
                logger.error(f"OpenAI API error for final response: {str(e)}")
                error_message = f"Erro ao processar sua consulta: {str(e)}. Por favor, tente novamente mais tarde."
                conversation_history.append({
                    "role": "assistant",
                    "content": error_message
                })
                
                with conversation_lock:
                    # Update the conversation history in the shared dictionary
                    conversation_histories[session_id] = conversation_history
                
                return error_message
        
        # If no function call, return the original response
        with conversation_lock:
            # Update the conversation history in the shared dictionary
            conversation_histories[session_id] = conversation_history
        
        return response_message.content or "Desculpe, não consegui gerar uma resposta. Por favor, tente reformular sua pergunta."
    
    except Exception as e:
        error_message = f"Ocorreu um erro ao processar sua consulta: {str(e)}"
        logger.error(f"Error processing query: {error_message}")
        logger.error(traceback.format_exc())
        conversation_history.append({
            "role": "assistant",
            "content": error_message
        })
        
        with conversation_lock:
            # Update the conversation history in the shared dictionary
            conversation_histories[session_id] = conversation_history
        
        return error_message


# Flask routes

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html', courts=list(COURTS.keys()))


@app.route('/api/chat', methods=['POST'])
def chat_api():
    """API endpoint for chat interactions."""
    try:
        # Get request data
        try:
            data = request.json
            if not data:
                return jsonify({"error": "Invalid JSON payload"}), 400
        except Exception as e:
            logger.error(f"Error parsing request JSON: {str(e)}")
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        # Extract query and session_id
        query = data.get('query')
        session_id = data.get('session_id', request.remote_addr)
        
        if not query:
            return jsonify({"error": "Query is required"}), 400
        
        # Log the incoming request
        logger.info(f"Chat request from {session_id}: {query[:100]}...")
        
        # Run the agent with timeout
        try:
            response = run_agent(query, session_id)
        except Exception as e:
            logger.error(f"Error running agent: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({
                "error": f"Erro ao processar sua consulta: {str(e)}",
                "session_id": session_id
            }), 500
        
        # Return the response
        return jsonify({
            "response": response,
            "session_id": session_id
        })
    
    except Exception as e:
        logger.error(f"Unhandled error in chat API: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Erro interno do servidor: {str(e)}"}), 500


@app.route('/api/process/<process_number>')
def get_process_api(process_number):
    """API endpoint to get process information."""
    try:
        court = request.args.get('court')
        result = get_process_status(process_number, court)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in process API: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route('/api/movements/<process_number>')
def get_movements_api(process_number):
    """API endpoint to get process movements."""
    try:
        court = request.args.get('court')
        limit = request.args.get('limit', 10, type=int)
        
        if not court:
            return jsonify({"error": "Court parameter is required"}), 400
        
        result = get_process_movements(process_number, court, limit)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in movements API: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route('/api/search')
def search_api():
    """API endpoint to search for processes by class and judge."""
    try:
        class_code = request.args.get('class_code', type=int)
        judge_code = request.args.get('judge_code', type=int)
        court = request.args.get('court')
        limit = request.args.get('limit', 10, type=int)
        
        if not all([class_code, judge_code, court]):
            return jsonify({"error": "class_code, judge_code, and court parameters are required"}), 400
        
        result = search_by_class_and_judge(class_code, judge_code, court, limit)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in search API: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route('/api/details/<process_number>')
def get_details_api(process_number):
    """API endpoint to get detailed process information."""
    try:
        court = request.args.get('court')
        
        if not court:
            return jsonify({"error": "Court parameter is required"}), 400
        
        result = get_process_details(process_number, court)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in details API: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    return jsonify({
        "status": "ok", 
        "version": "1.0.1",
        "openai_api_key_set": bool(OPENAI_API_KEY),
        "datajud_api_key_set": bool(API_KEY),
        "courts_available": list(COURTS.keys())
    })


# Create templates directory and index.html
@app.before_first_request
def create_templates():
    """Create templates directory and index.html if they don't exist."""
    import os
    
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    index_html = os.path.join(templates_dir, 'index.html')
    
    if not os.path.exists(index_html):
        with open(index_html, 'w', encoding='utf-8') as f:
            f.write('''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Assistente Jurídico DataJud</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f8f9fa;
            padding-bottom: 50px;
        }
        .chat-container {
            max-width: 800px;
            margin: 0 auto;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        .chat-header {
            background-color: #0d6efd;
            color: white;
            padding: 15px 20px;
            font-weight: bold;
            font-size: 1.2rem;
        }
        .chat-messages {
            height: 400px;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
        }
        .message {
            margin-bottom: 15px;
            max-width: 80%;
            padding: 10px 15px;
            border-radius: 10px;
            position: relative;
        }
        .user-message {
            align-self: flex-end;
            background-color: #0d6efd;
            color: white;
            border-bottom-right-radius: 0;
        }
        .assistant-message {
            align-self: flex-start;
            background-color: #f1f1f1;
            color: #333;
            border-bottom-left-radius: 0;
        }
        .chat-input {
            padding: 15px;
            border-top: 1px solid #e9e9e9;
            display: flex;
        }
        .chat-input input {
            flex-grow: 1;
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 5px 0 0 5px;
            outline: none;
        }
        .chat-input button {
            border-radius: 0 5px 5px 0;
        }
        .loading {
            align-self: center;
            margin: 10px 0;
            color: #666;
            font-style: italic;
        }
        .examples {
            margin-top: 30px;
            padding: 20px;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
        }
        .example-btn {
            margin: 5px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .example-btn:hover {
            transform: translateY(-2px);
        }
        .info-section {
            margin-top: 30px;
            padding: 20px;
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.1);
        }
        pre {
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
        .white-space-pre-wrap {
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="container mt-5">
        <h1 class="text-center mb-4">Assistente Jurídico DataJud</h1>
        <p class="text-center mb-4">Consulte informações processuais dos tribunais brasileiros usando inteligência artificial.</p>
        
        <div class="chat-container">
            <div class="chat-header">
                <div class="d-flex justify-content-between align-items-center">
                    <span>Chat com Assistente Jurídico</span>
                    <button id="clear-chat" class="btn btn-sm btn-outline-light">Limpar Chat</button>
                </div>
            </div>
            <div class="chat-messages" id="chat-messages">
                <div class="message assistant-message">
                    Olá! Sou seu assistente jurídico especializado em consultar o DataJud. Como posso ajudar hoje?
                </div>
            </div>
            <div class="chat-input">
                <input type="text" id="user-input" placeholder="Digite sua pergunta aqui..." class="form-control">
                <button id="send-btn" class="btn btn-primary">Enviar</button>
            </div>
        </div>
        
        <div class="examples">
            <h4>Exemplos de perguntas:</h4>
            <div class="d-flex flex-wrap">
                <button class="btn btn-outline-primary example-btn">Qual o status do processo 00008323520184013202?</button>
                <button class="btn btn-outline-primary example-btn">Quais são os movimentos do processo 00008323520184013202 no TRF1?</button>
                <button class="btn btn-outline-primary example-btn">Busque processos da classe 1116 no órgão julgador 13597 no TJSP</button>
                <button class="btn btn-outline-primary example-btn">Me dê detalhes completos do processo 00008323520184013202</button>
            </div>
        </div>
        
        <div class="info-section">
            <h4>Tribunais suportados:</h4>
            <ul>
                <li>Tribunal de Justiça de São Paulo (TJSP)</li>
                <li>Tribunal Superior de Justiça (STJ)</li>
                <li>Tribunais Regionais Federais (TRF1-6)</li>
            </ul>
            
            <h4>API Endpoints:</h4>
            <pre><code>GET  /api/process/:numero?court=TJSP
GET  /api/movements/:numero?court=TJSP&limit=10
GET  /api/details/:numero?court=TJSP
GET  /api/search?class_code=1116&judge_code=13597&court=TJSP&limit=10
POST /api/chat
    {"query": "texto da pergunta", "session_id": "opcional"}</code></pre>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const chatMessages = document.getElementById('chat-messages');
            const userInput = document.getElementById('user-input');
            const sendBtn = document.getElementById('send-btn');
            const clearChatBtn = document.getElementById('clear-chat');
            const exampleBtns = document.querySelectorAll('.example-btn');
            
            let sessionId = Date.now().toString();
            let isWaitingForResponse = false;
            
            function addMessage(text, isUser) {
                const messageDiv = document.createElement('div');
                messageDiv.className = isUser ? 'message user-message' : 'message assistant-message';
                messageDiv.innerHTML = `<span class="white-space-pre-wrap">${text}</span>`;
                chatMessages.appendChild(messageDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
            
            function showLoading() {
                const loadingDiv = document.createElement('div');
                loadingDiv.className = 'loading';
                loadingDiv.id = 'loading-indicator';
                loadingDiv.textContent = 'Assistente está digitando...';
                chatMessages.appendChild(loadingDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
            
            function hideLoading() {
                const loadingDiv = document.getElementById('loading-indicator');
                if (loadingDiv) {
                    loadingDiv.remove();
                }
            }
            
            function sendMessage() {
                const text = userInput.value.trim();
                if (!text || isWaitingForResponse) return;
                
                addMessage(text, true);
                userInput.value = '';
                showLoading();
                isWaitingForResponse = true;
                
                // Disable send button while waiting
                sendBtn.disabled = true;
                
                fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        query: text,
                        session_id: sessionId
                    })
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    hideLoading();
                    addMessage(data.response, false);
                })
                .catch(error => {
                    hideLoading();
                    addMessage('Erro ao processar sua solicitação: ' + error.message, false);
                    console.error('Error:', error);
                })
                .finally(() => {
                    isWaitingForResponse = false;
                    sendBtn.disabled = false;
                });
            }
            
            sendBtn.addEventListener('click', sendMessage);
            
            userInput.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });
            
            clearChatBtn.addEventListener('click', function() {
                // Only allow clearing if not waiting for a response
                if (isWaitingForResponse) return;
                
                // Clear all messages except the first one (welcome message)
                while (chatMessages.children.length > 1) {
                    chatMessages.removeChild(chatMessages.lastChild);
                }
                
                // Generate new session ID
                sessionId = Date.now().toString();
            });
            
            exampleBtns.forEach(btn => {
                btn.addEventListener('click', function() {
                    if (isWaitingForResponse) return;
                    userInput.value = this.textContent;
                    sendMessage();
                });
            });
        });
    </script>
</body>
</html>
            ''')


if __name__ == '__main__':
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 8080))
    
    # Check if OpenAI API key is set
    if not OPENAI_API_KEY:
        print("Aviso: OPENAI_API_KEY não está configurada.")
        print("Por favor, configure a variável de ambiente OPENAI_API_KEY antes de iniciar o serviço.")
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=port, debug=False)
