# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Comparação de capacidade fixa e adaptativa concluída; consolidação da candidata
`v1.1.0-rc.1` preparada para revisão.** Branch `feature/v1.1-autoscaling-kind`.
Nenhuma nova tag ou GitHub Release foi criada. A publicação e o merge aguardam
confirmação após leitura dos documentos e conferência dos pacotes.

As nove tentativas foram preservadas, incluindo a primeira adaptativa da sessão
interrompida. A continuação terminou com zero posições pendentes. Não há nova
carga autorizada por este fechamento. Resultados, método, sensibilidade e limites
estão no [relatório de capacidade](docs/SCALING_EVALUATION.md); os três ZIPs em
`docs/evidence/scaling/archives` eliminam a dependência de pastas locais para sua
leitura. A imagem, o código da aplicação e o instrumento medido permanecem congelados.

## 2. Entregas e responsabilidades

| Referência | Entrega e situação |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação operacional em Kind; [relatório e evidências](docs/OPERATIONAL_EVALUATION.md) preservados |
| Candidata v1.1.0-rc.1 | Capacidade fixa/adaptativa, scripts versionados, comparação concluída, gráficos e três pacotes para revisão |
| Aplicação consumida | FulfillFlow v1.3.0-rc.1, SHA `9e3a135a00db218643633c7165d3106f0c8285e1`; nenhuma alteração neste fechamento |
| Azure | Terraform e exemplos AKS/ACR são referências ainda não implantadas; não condicionam o aceite local |

README apresenta a entrega e orienta a navegação. DESIGN define contratos e
arquitetura. O guia `k8s/README.md` reúne pré-requisitos e comandos. Os relatórios
registram métodos executados, resultados e respectivas evidências. Este documento
acompanha estado de entrega e decisões futuras, sem duplicar as tabelas analíticas.

## 3. Revisão da candidata

- Conferir o [relatório](docs/SCALING_EVALUATION.md), incluindo as nove tentativas,
  a interrupção do bloco 1 e a leitura dos blocos contínuos, sem excluir tardios.
- Conferir os [três pacotes e checksums](docs/evidence/scaling/archives), o
  [manifesto](docs/evidence/scaling/manifest.json) e a reprodução offline. A
  qualificação tem seleção de metadados; não é apresentada como pacote bruto integral.
- Conferir a distinção entre protocolo/SHAs medidos e commit de consolidação;
  scripts de execução permanecem em `scripts/`, sem depender de launchers `.local.ps1`.
- Registrar validação da documentação e do reprodutor, revisão visual e inspeção
  de conteúdo publicável. Conferir CI da referência antes da eventual publicação;
  CI não executa a comparação no Kind.
- Depois do aceite explícito, criar `v1.1.0-rc.1` no commit conferido e publicar a
  release com os mesmos três ZIPs e seus checksums. Revisar antes de integrar a branch.

A [nota da candidata](docs/releases/v1.1.0-rc.1.md) está preparada para essa etapa;
não é registro de uma release já publicada. A versão identifica a infraestrutura,
independentemente da numeração da aplicação. Não mover tags nem substituir pacotes
publicados. Uma correção posterior deve ter identidade própria.

<a id="3-extensões-possíveis"></a>

## 4. Continuidade condicionada

O próximo passo pode ser encerrar a evolução neste recorte, investigar observabilidade
ou verificar portabilidade. Nenhuma alternativa é requisito para concluir a candidata.
As [questões e critérios técnicos](docs/SCALING_EVALUATION.md#6-interpretação-conjunta-e-continuidade)
orientam a decisão; não há compromisso de instalar todas as ferramentas.

**Observabilidade:** se escolhida, iniciar `feature/v1.2-observability` a partir da
referência revista. Fazer uma verificação pequena de correlação entre aceitação,
conclusão por etapa e confirmação pelo observador. Continuar somente se acrescentar
diagnóstico verificável com custo aceitável. Não prometer uma campanha completa,
uma nova release ou explicação retrospectiva dos 503. Alteração de instrumentação
ou dependências exige referência própria da aplicação/runtime. Prometheus e
verificações de segurança permanecem opções justificadas por lacuna concreta.

**AKS:** extensão opcional de portabilidade e funcionamento selecionado, com prints
e evidências do ambiente efetivamente usado. ACR depende da implantação escolhida.
Os resultados quantitativos do Kind não se tornam resultados de nuvem. Uma
comparação correspondente no AKS exigiria protocolo e repetições próprios;
instrumentação e ambiente não devem mudar juntos numa comparação que pretenda
atribuir efeito somente à instrumentação.

As consultas anteriores não estabeleceram uma configuração Azure provisionável.
Antes de qualquer apply, revisar assinatura, região, quotas, restrições de SKU,
capacidade, acesso, orçamento, encerramento e custos residuais conforme o
[guia Terraform](infra/README.md). Quota positiva não garante alocação. Não iniciar
nuvem, alterar limites de carga ou refatorar a aplicação a partir desta consolidação.

## 5. Preservação e histórico

Os relatórios substituem o diário preparatório na leitura principal. O
[histórico completo até o encerramento](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
continua acessível por commit imutável; as pastas originais permanecem intactas.
Identificadores como `a2-*`, `b1-p1-*` e nomes históricos de scripts são mantidos
somente para rastrear protocolos e arquivos. Não representam novos incrementos pendentes.

As três pastas de tentativas em cada ZIP são completas. Configurações privadas,
credenciais, dumps e kubeconfigs continuam fora do Git. Os pacotes permitem
conferir dados e gráficos sem o notebook original; não incluem imagem Docker nem
garantem recriação idêntica de hardware/runtime ou restauração de backup independente.
Novas medições exigem ambiente e protocolo identificados, diretórios novos e
encerramento limitado, preservando resultados desfavoráveis e falhas de execução.

Versões seguem a convenção: correções compatíveis incrementam PATCH, capacidades
compatíveis MINOR e mudanças incompatíveis MAJOR; candidatas usam `-rc.N`.
Não reservar automaticamente uma versão para cada ferramenta ou ambiente.
