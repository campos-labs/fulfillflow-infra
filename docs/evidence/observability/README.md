# Evidências de observabilidade

Método, interpretação, figuras e limites: [avaliação de observabilidade](../../OBSERVABILITY_EVALUATION.md).
Este índice identifica arquivos e reprodução; não contém uma segunda análise.

| Pacote | Conteúdo e natureza |
| --- | --- |
| [correlation.zip](archives/correlation.zip) | 20 capturas selecionadas dos dois casos de workers e da preparação, manifesto original e dois resumos derivados; descoberta retrospectiva identificada como contexto |
| [http.zip](archives/http.zip) | 34 capturas selecionadas: saudável 05, erros preparatórios 02/03 e sequência controlada 03; respectivos manifestos |
| [packages.json](packages.json) | SHA-256 dos ZIPs e de cada entrada; fontes, representação e hashes dos diagramas |

Cada ZIP contém um `INDEX.md` curto. Registros permanecem legíveis no GitHub em
[records](records/), [http-05](http-05/), [http-errors](http-errors/) e
[http-fault-03](http-fault-03/). Os ZIPs transportam os mesmos dados, não novos resultados.
Capturas preservam seus bytes; metadados derivados da raiz usam LF no pacote para
reprodução em Windows/Linux. `review.json` é conferência, não registro original.

O [manifesto de correlação](manifest.json) e os manifestos HTTP declaram seleção e
exclusões. Imagens, bancos, segredos, configuração privada, séries completas de host
e tentativas não selecionadas continuam fora dos pacotes. Um hash de fonte local
num resumo não significa que essa fonte esteja publicada.

Na raiz do checkout, sem Docker nem arquivos privados:

```powershell
uv run --frozen python docs/evidence/observability/reproduce.py
```

Usar `--write` somente para regenerar ZIPs, índice de hashes e SVGs dos dados atuais.
A execução padrão apenas confere. Os scripts experimentais estão versionados em
`scripts/`; os pacotes permitem inspecionar resultados, não recriar o laboratório.

<a id="cobertura-e-limites"></a>
<a id="método-e-resultados"></a>
<a id="evidências-examináveis"></a>
<a id="preparação-preservada"></a>
<a id="decisão"></a>
<a id="fatia-http-com-opentelemetry"></a>
<a id="erros-preparatórios-http-preservados"></a>
<a id="falha-http-controlada-e-recuperação"></a>
As seções analíticas antes presentes neste endereço foram consolidadas no
[relatório técnico](../../OBSERVABILITY_EVALUATION.md); os registros originais não mudaram.
