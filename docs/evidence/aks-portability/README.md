# Evidências de portabilidade AKS

O [relatório técnico](../../AKS_PORTABILITY_EVALUATION.md) concentra método,
resultados, interpretação e limites. Este índice trata apenas dos arquivos.

| Pacote | Conteúdo |
| --- | --- |
| [portability.zip](archives/portability.zip) | Smoke, tentativas de persistência, volumes, rede, ambiente, digests, regressão Kind e captura de workloads |
| [http-and-closure.zip](archives/http-and-closure.zip) | Recusa de capacidade, OTel isolado, restauração, inventário final e captura pós-remoção |

Os [registros JSON](records) estão também legíveis sem descompactar. O
[manifesto](manifest.json) lista seleção, transformação aplicada, tamanho, hash
público e hash da fonte privada. Cada ZIP contém esse manifesto global; seus
subconjuntos são os grupos indicados acima, não todos os arquivos do manifesto.
As imagens reais foram recortadas no momento da captura para excluir cabeçalhos
da conta e copiadas sem alteração. Arquivos originais privados, state, credenciais,
imagens de runtime e dados completos não estão incluídos.

Os [checksums dos ZIPs](archives/checksums.sha256) e [derivados](packages.json)
permitem conferir integridade. Na raiz de um checkout desta revisão, com Python
3.12 e biblioteca padrão:

```powershell
python docs/evidence/aks-portability/reproduce.py
```

A verificação confronta os registros e os contratos públicos de persistência e
tracing; reproduz em memória ZIPs/diagrama e exige igualdade de bytes. Não acessa
Azure, Docker ou arquivos privados. `--write` regenera somente os derivados a
partir dos registros e manifesto existentes. Hashes não comprovam por si sós a
origem ou a completude dos dados; as projeções preservam somente o recorte descrito.

Os auxiliares estão em [scripts/azure](../../../scripts/azure). Os orquestradores
locais executados são identificados em [execution-sources.json](records/execution-sources.json),
sem expor configuração privada. O pacote permite revisar os resultados; não
reconstitui automaticamente a janela Azure nem oferece backup da aplicação.
