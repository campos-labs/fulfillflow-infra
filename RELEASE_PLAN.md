# FulfillFlow Infra — Plano de implantação funcional

## 1. Objetivo, estado e limites

**Estado atual: A1 concluído; A2 em Kind selecionado e planejado em dois incrementos.**
A2 ainda não está implementado nem medido. A preparação documental não representa
execução: o laboratório permanece parado e as evidências L4/A1 estão preservadas.

O ciclo atual entrega restauração automatizada delimitada e comparação com
acionamento explícito, mantendo a aplicação congelada e réplicas fixas. Kind é o
ambiente principal; AKS/ACR e autoescalonamento (B) são extensões opcionais, sem
bloquear o encerramento. Os incrementos II–IV de Azure abaixo permanecem reservados
à nuvem e são distintos dos dois incrementos A2 da seção 7.

| Etapa | Estado |
| --- | --- |
| Base documental e validação estática | Concluídas; plano A2 atualizado |
| L1–L4 e A1 | Aceites locais concluídos; laboratório parado e dados preservados |
| A2-I — Política de restauração e piloto | Planejado; implementação pendente |
| A2-II — Comparação delimitada e encerramento | Planejado; depende do aceite A2-I |
| II–IV — Azure | Não iniciados; opcionais, fora do ciclo atual |
| B — Autoescalonamento | Não selecionado; fora do ciclo atual |

As condições e os limites aprovados estão na seção 7 e no DESIGN §8.5. Resolver
ajustes pequenos dentro do incremento; mudanças de aplicação, cenário, permissões,
custos ou dados exigem reavaliação. Campanhas extensas de desempenho da aplicação
continuam suspensas; a comparação A2 é operacional e delimitada.

### Caminho local — aceite em 21/09/2026

O caminho Kind permite a pausa com aceite funcional local, sem exigir implantação
prévia no AKS. Não encerra os incrementos II–IV de nuvem. A seleção ambiental Azure
e seu bloqueio estão registrados na seção 3.

Etapas executadas:

1. **L1 — Cluster isolado:** Kind portátil e imagem de nó fixados, checksum
   conferido, kubeconfig próprio e API em loopback; recursos alheios preservados.
2. **L2 — Implantação local:** imagem do SHA congelado reconstruída sem alterar
   aplicação/lock; credenciais exclusivas, PVCs novos e migrations sequenciais
   antes das três APIs e três workers.
3. **L3 — Aceite local:** cenários da seção 6 com dados sintéticos novos, prazos
   finitos e evidências por cenário; nenhuma campanha ou comparação com AKS.
4. **L4 — Pausa:** identidade, resultados e limites consolidados; evidências e
   dumps exportados; workloads e nó parados, com dados preservados.

O perfil e suas diferenças em relação ao AKS são definidos no DESIGN, seções 7 e
10; ferramentas em `config/kind-toolchain.json`. A execução usou Docker/WSL com
cgroup v1 e Kubernetes 1.34.0, em janela delimitada. Não é recomendação de versão
para a nuvem nem ensaio de capacidade do notebook.

**Estado do marco anterior: L1–L3 concluídos; L4 atingido em 21/09/2026.**
Kind iniciou, oito componentes ficaram prontos e os três heads foram verificados:
`1301_core`, `1203_tracking`, `1301_notifications`. Imagem reconstruída do SHA
congelado, sem alteração de código/lock; identidade no pacote de evidências.

| Cenário local | Resultado e limite |
| --- | --- |
| Jornada + duplicata | 202 → Tracking concluído → Order FULFILLED → Notification SIMULATED; uma duplicata preservou identidades e efeito único |
| Core worker parado | Evento admitido permaneceu pendente e concluiu após retomada, sem novo webhook; parada anterior à admissão, não exatamente após ACK |
| Mesmo ID, outro conteúdo assinado | 409 e registro original preservado; efeitos continuaram únicos |
| Notifications pausado | Tracking/Order concluíram com simulação pendente; retomada concluiu sem novo webhook |
| Broker recriado com trabalho pendente | Novo UID, mesmo PVC, conclusão posterior única; cenário combinado, sem atribuição causal isolada ao broker |
| API Notifications parada | Consulta retornou 503, sem lista vazia; observação retomada preservou o evento |
| PostgreSQL recriado | Novo UID, mesmos PVCs, identidades/resultados/efeitos preservados; não representa falha do host |

Verificações: 54 testes Python, Ruff/formatação, nove renderizações com schemas e
16 testes Terraform com provider simulado aprovados. Admissão e execução reais
ocorreram no API server local 1.34.0; schemas estáticos permanecem 1.35.0.
A [CI Linux/Windows](https://github.com/campos-labs/fulfillflow-infra/actions/runs/35564908760)
foi aprovada no SHA de infraestrutura `d98adda9a27a3b6d0adb1b55e5cc51c674ce20d9`.
Ela executa validações estáticas, unitárias e planos simulados; os cenários no
cluster foram executados localmente, fora da CI.

Pacote local não versionado: `artifacts/kind-functional-01/summary.json`,
`acceptance-results.json`, observações JSONL, manifests efetivos, heads, imagens e
`checksums.json` (23 arquivos). O fechamento está em
`artifacts/kind-functional-01-closure.json`. `acceptance_local.py` registra o
procedimento adicional de recuperação; contém caminhos locais e não é um runner
portátil ou etapa da CI. Cópia adicional foi conferida no mesmo computador. Dumps dos três bancos foram exportados em
diretório protegido fora do Git; restauração independente não foi exercitada.
Não chamar cópia no mesmo host de proteção contra perda do equipamento.

NetworkPolicies têm suporte no Kind fixado, mas os cenários de permissão/bloqueio
de tráfego não foram ensaiados. Essa lacuna permanece distinta das verificações
Azure e não invalida os resultados funcionais delimitados acima.

Na pausa, os seis Deployments e os dois StatefulSets foram escalados a zero e o
container `fulfillflow-local-01-control-plane` foi parado. PVCs, imagens, recursos
históricos e credenciais foram preservados. A retomada do mesmo ambiente segue
[k8s/README.md](k8s/README.md#instalação-e-operação-local); não é nova instalação.

O A1 concluído e o planejamento A2 na seção 7 não alteram o aceite anterior.
Trials, conversão de assinatura, provisionamento Azure e publicação de tag/release
continuam fora da execução local aprovada.

## 2. Regras de execução deste plano

1. Ler o estado atual e as seções pertinentes do DESIGN antes de cada incremento.
2. Preservar a referência da aplicação e suas evidências. Correções rotineiras de
   documentação, caminhos, diagnóstico e automação pertencentes ao incremento
   podem avançar com testes focais; mudanças de contrato exigem decisão específica.
3. Implementar e revisar por incremento, com testes desde a primeira mudança
   executável. Não interromper a cada arquivo; consolidar dúvidas que realmente
   mudem custo, acesso, persistência, arquitetura ou escopo.
4. Integrar alterações diretamente na `main`, em commits por assunto, após revisão
   do diff e validações pertinentes. Registrar o resultado da CI quando implementada.
   A CI da aplicação permanece no seu repositório.
5. Manter operação utilizável em PowerShell. Conferir executáveis instalados,
   versões, diretório corrente e caminhos com espaços. Não presumir `pwsh`, Azure
   CLI ou Terraform no PATH; não instalar/atualizar ferramentas silenciosamente.
6. Validar configuração e revisar plano antes de apply. Registrar alvo e propriedade
   dos recursos; não usar administração global como atalho para falha de permissão.
   Tratar saída sensível fora do Git e dos logs públicos.
7. Toda operação tem prazo, saída explícita, identificação e diagnóstico preservado.
   Parar mutações na primeira falha inesperada; falhas deliberadas do piloto seguem
   a observação e o encerramento definidos no DESIGN. Não substituir tentativa
   inválida ou reexecutar a sequência automaticamente. Uma correção exige causa
   classificada e tentativa sucessora identificada, sem apagar o registro anterior.
8. Não repetir suítes aprovadas sem mudança ou dúvida concreta. Ao terminar cada
   incremento, registrar diff, checks, SHA, evidências, limitações e próximo passo.
   Fornecer comando manual apenas quando houver uma operação manual necessária,
   preparada e autorizada, com duração, destino e comportamento de interrupção.
9. Não versionar segredos, planos/state Terraform, kubeconfigs, dumps ou logs brutos.
   Verificar diff e ignorados antes de cada commit. Exemplos usam placeholders;
   códigos/IDs técnicos em inglês e documentação técnica concisa em português.
10. Não criar documentos de contexto redundantes. README orienta o uso; DESIGN
    define arquitetura; este plano registra andamento e decisões de continuidade.

## 3. Incremento I — Preparação e validação local

**Entrega:** estrutura mínima executável, CI de validação e ficha de ambiente,
sem provisionamento Azure.

- Conferir ferramentas e fixar versões compatíveis de Terraform/provider,
  kubectl e helpers realmente necessários. Fixar Azure CLI antes do preflight
  conectado, sem instalá-la como requisito da validação offline. Não depender de versões
  `latest`; registrar locks quando houver implementação.
- Definir assinatura, região, quotas, teto de gasto e período de operação;
  dimensionar nós/discos com margem para sistema, rollout e Jobs. Não transportar
  o orçamento do benchmark histórico como se fosse orçamento do cluster.
- Preparar módulos/configuração Terraform mínimos para bootstrap e ambiente;
  manifests de runtime com dados não sensíveis e configuração de exemplo.
- Resolver acesso do executor ao cluster/ACR/backend, endpoint Kubernetes,
  modelo de secrets e retenção de dados. Consolidar essas decisões antes de apply.
- Implantar CI sem credenciais de cloud para validação de documentos, Terraform
  e manifests presentes. Fixar revisões de actions e permissões mínimas.
- Preparar o verificador funcional com códigos de saída, polling e timeouts
  explícitos. Não adaptar o loadgen síncrono nem criar campanha de carga.

**Verificação:** links e `git diff --check`; Terraform fmt/validate com provider
fixado e sem backend remoto; renderização Kustomize e validação contra schemas
compatíveis; testes focais do verificador e dos scripts, incluindo PowerShell real
quando houver scripts PowerShell. Validação estática não comprova deploy.

**Aceite:** CI do commit aprovada, decisões do ambiente registradas, planos de
bootstrap e configuração revisáveis, sem segredos. Falta de ferramenta ou quota
é pendência explícita, não aprovação substituída por mocks.

### Estado da preparação

Preparados dois roots Terraform (backend e ambiente), locks Windows/Linux,
manifests separados em fundações/migrações/runtime, ficha sem valores de assinatura,
verificador público de conclusão/duplicata e CI de validação sem credenciais cloud.
O exemplo de runtime tem imagem inválida e seletor que impede agendamento.
O overlay Kind tem aceite local; não existe workflow de deploy Azure, overlay
AKS aprovado ou imagem publicada no ACR.

Versões e hashes ficam em `config/toolchain.json` e nos locks. Os testes do
verificador usam transporte controlado; Terraform usa provider simulado somente
em planos. Nenhum desses resultados constitui execução funcional no AKS.

Os resultados atuais e a CI estão na seção 1. Os testes Terraform de ambiente
selecionam recursos por limitação do mock de `kubelet_identity`; a atribuição
`AcrPull` exige conferência real posterior, conforme [infra/README.md](infra/README.md).

O aceite ambiental Azure depende de assinatura/benefício e saldo efetivos, região,
quotas/SKUs, janela e teto de gasto, capacidade alocável, conectividade do executor,
endpoint, canal de secrets e destino protegido de evidências. Os campos Azure
ausentes em `config/environment.json` não são defaults nem registro das consultas
históricas. A preparação não autoriza provisionamento durante a pausa.

### Recursos e seleção ambiental Azure

`k8s/overlays/reduced-functional` mantém os bloqueios de agendamento e imagem do
exemplo AKS. Seus requests são os definidos no DESIGN, seção 7, também usados no
Kind: 1900m/5376 MiB de runtime e 250m/384 MiB por Job. Não são mínimos medidos;
o aceite sequencial local não demonstra capacidade, ausência de throttling ou
comportamento sob carga. Ampliar recursos exige nova identidade e verificação.

**Consultas encerradas em 20/09/2026:** cotas positivas não identificaram, por si
só, um candidato alocável. As validações encontraram restrição de regiões e recusa
explícita de `Standard_D4s_v3` pelo AKS em Canada Central. As regiões permitidas
consultadas foram Brazil South, Canada Central, North Central US, Mexico Central
e Spain Central. A tentativa de pedido de cota pelo portal não gerou protocolo;
falha de interface não é aprovação nem recusa de suporte. Nenhum recurso cobrado
do projeto foi criado nessas tentativas.

As instruções superadas de busca e suporte permanecem no histórico Git. Novas
buscas, provisionamentos, conversão de assinatura e trials ficam suspensos até
a decisão da seção 9. A reserva de US$40 para etapa posterior permanece como
restrição de planejamento, não autorização para consumir o restante do saldo.
Créditos, quotas, disponibilidade e preços devem ser reconferidos na retomada.

Antes de apply Azure, confirmar suporte ao pool/versão, quotas regional e de
família, SKU, capacidade alocável, componentes de sistema, Jobs, rede, secrets,
armazenamento e custo. Menor request de pods não reduz a cota de vCPUs dos nós.
Não adotar nó único ou reduzir proteções de manutenção para contornar um bloqueio.

### Manutenção da proposta AKS

A proposta mantém nós fixos, autoscaling desabilitado,
`node_os_upgrade_channel = "None"` e `max_surge = "1"`. A janela funcional não
inclui upgrades ou rotação planejados; isso não impede reparos do serviço nem
constitui política permanente de atualização. Incluir o nó temporário nas cotas
e no custo antes de autorizar manutenção.

Revisar qualquer atualização, substituição ou uso de `temporary_name_for_rotation`
no plano Terraform. Falta de capacidade exige reavaliação, sem troca automática
de SKU ou retry. Surge de nós é distinto de `maxSurge` dos Deployments. Os detalhes
da configuração e encerramento pertencem a [infra/README.md](infra/README.md).

## 4. Incremento II — Bootstrap Azure e imagens

**Pré-condição:** incremento I aceito; alvo, custo e permissões das operações
concretas autorizados.

- Criar backend remoto e recursos de suporte com separação da infraestrutura
  removível. Verificar locking e acesso ao state, sem publicá-lo como artefato.
- Criar grupo de recursos, ACR e identidades/federação necessários. Aplicar
  permissões mínimas; manter login humano separado da identidade de automação.
- Configurar alertas de custo e procedimento de encerramento com recursos ainda
  cobrados identificados. Não tratar alertas como bloqueio automático de gastos.
- Publicar imagens da referência por fluxo auditado do repositório da aplicação;
  preservar Dockerfile e lock. Registrar eventuais mudanças do workflow de
  publicação separadamente do SHA construído, sem mover a tag da aplicação.
- Inventariar os digests de runtime, PostgreSQL e RabbitMQ, origens, plataforma,
  configuração de acesso e retenção. Guardar logs de build/smoke sanitizados.

**Verificação:** autenticação OIDC no escopo definido, escrita/leitura autorizada
do backend, publicação e pull por digest, smoke da imagem e correspondência
source/lock. O sucesso da CI antiga não substitui o smoke da imagem reconstruída.

**Aceite:** backend protegido, imagens identificadas e recursos inventariados.
Convite da equipe permanece adiado para a pausa; não criar contas compartilhadas.

## 5. Incremento III — AKS e implantação

**Pré-condição:** incremento II aceito e plano de criação do cluster autorizado.

- Provisionar AKS, nós fixos, rede, identidades e armazenamento conforme DESIGN.
  Registrar configuração efetiva e custo previsto; não ativar autoscaling.
- Aplicar namespace, políticas, secrets por canal protegido e workloads. Provisionar
  bancos/roles e broker com identidade persistente e credenciais próprias.
- Executar e verificar os três Jobs de migração antes de runtime; preservar
  falhas, não apagar volumes para fazer o startup passar.
- Configurar probes com semântica correta, sinais de shutdown, requests/limits
  e margem dos nós. Healthcheck do worker não vira liveness de dependências.
- Entregar deploy explícito via GitHub Actions, sem rollback automático ou Argo
  CD. Resolver a conectividade do executor sem afrouxar exposição de rede.
- Executar smoke funcional com dados novos e acesso restrito ao Core.

**Verificação:** conexão dos processos somente aos bancos/filas autorizados,
migrations/heads, pods, probes, pull, endpoints internos e jornada assíncrona.
Reaplicar a mesma configuração sem alterações inesperadas; registrar como o
ambiente pode ser reconstruído, sem exigir destruição de dados existentes.

**Aceite:** implantação identificada e reproduzível; jornada concluída no AKS;
pipeline e operação manual coerentes; nenhuma declaração de capacidade ou HA.

## 6. Incremento IV — Aceite funcional e pausa

Executar verificações curtas em recursos de propriedade deste ambiente. Definir
antes de cada cenário IDs, pré-condições, prazo, resultado esperado e restauração
do estado operacional. Reinícios e pausas deliberadas são ações explícitas; não
habilitar injeção contínua de falhas ou carga extensa.

| Cenário | Critério de aceite |
| --- | --- |
| Jornada saudável | Aceite durável, Tracking concluído, estado esperado de Shipment/Order e Notifications `SIMULATED` consultáveis |
| Duplicata | Mesmo ID/bytes não acrescenta efeito ou simulação; resultado original preservado |
| Conflito | Mesmo ID com bytes diferentes é rejeitado sem sobrescrever o original |
| Worker interrompido | Trabalho aceito e pendente retoma após reinício, sem novo webhook e sem duplicação; o registro identifica o ponto observado |
| Notifications pausado | Tracking/Order podem concluir; pendência é visível e a simulação termina após retomada |
| Persistência | Recriação controlada de pod de banco/broker preserva dados e identidade, com retorno funcional verificado |
| Consulta indisponível | Diagnóstico distingue erro de consulta, prazo esgotado, rejeição e pendência; não converte falha em lista vazia/sucesso |

Estes critérios servem ao aceite local L3 e, em execução própria, ao IV no AKS.
Não alegar falha exatamente após commit/ACK apenas por matar um pod em horário
aproximado. Usar evidência que localize o ponto ou limitar a conclusão à retomada
observada. Testes existentes da aplicação são complementares, não execução no AKS.
Trabalho `BLOCKED` não é recuperação automática: registrar diagnóstico/rearme
autorizado quando pertinente, sem alterar tabelas manualmente.

Preparar um registro curto de aceite com SHAs, digests, heads, topologia efetiva,
parâmetros, cenários, resultados, localização dos originais e limitações. Exportar
e verificar cópia independente das evidências e dados necessários; lacunas de
backup/restauração permanecem explícitas. Atualizar README apenas com comandos
realmente executáveis e estados observados.

**Marco de pausa:** aceite funcional local (L4) ou aceite no AKS, sempre identificado
como tal, e pacote rastreável entregue. L4 pode ocorrer antes dos incrementos Azure.
L4 e A1 foram atingidos; a continuidade local escolhida é A2, na seção 7.
Não iniciar B, ampliar recursos, provisionar Azure ou publicar release neste ciclo.
O aceite funcional pode ser registrado mesmo com limites conhecidos, desde que
nenhum requisito funcional obrigatório tenha falhado ou sido silenciosamente pulado.

Nesse marco, preparar o acesso individual da equipe por convite e roles delimitadas,
para autorização e verificação conjunta. Não associar permissão de colaborador no
GitHub a permissão automática na Azure. Definir se recursos serão mantidos, parados
ou removidos; pausa não autoriza consumo indefinido nem destruição de dados.

## 7. Evolução local — aceite A1 e entrega A2

**A1 concluído; sua pausa foi encerrada pela escolha de A2 em Kind.** Escopo A1 entregue:
operação portátil, registro funcional e verificação de uma revisão, conforme
DESIGN §8.1–8.4. A1 não é a avaliação completa da alternativa A e não escolhe
antecipadamente o ambiente da coleta. Aplicação, locks e referências congeladas
permanecem intactos; sem novas ferramentas de produção.

### Aceite A1 em Kind — 24/09/2026

Referência executada: `033c5834af1c267f9cb48c1555368f489c54177d`, com
[CI Linux/Windows aprovada](https://github.com/campos-labs/fulfillflow-infra/actions/runs/35959820295).
As 78 verificações locais passaram, incluindo 24 casos A1 e PowerShell real;
Ruff/formatação aprovados. Importação, proveniência e launcher também foram
conferidos em checkout limpo com espaços no caminho, no mesmo host.

| Etapa observada | Resultado |
| --- | --- |
| Retomada | Oito workloads prontos, com volumes/secrets existentes e migrations sem repetição |
| Revisão saudável | Candidata identificada; Tracking/Order e Notifications SIMULATED; duplicata sem efeito adicional |
| Restauração da revisão saudável | Hash do template original restabelecido; evento anterior conferido por leitura e evento novo concluído |
| DB_POOL_SIZE=0 no notifications-worker | Rejeição de inicialização confirmada no pod; implantação reprovada e cenário esperado aprovado |
| Restauração após falha | Template original restabelecido e novo fluxo completo aprovado |
| Encerramento | Oito workloads conferidos saudáveis antes da pausa, depois escalados a zero; nó parado, PVCs preservados |

Foram três eventos novos concluídos e três duplicatas intencionais verificadas.
Nenhum evento foi oferecido durante a falha de inicialização: a observação funcional
nessa condição foi explicitamente não executada. O cenário não demonstra benefício
adicional de detecção sobre o estado nativo do pod, nem recuperação de trabalho
aceito enquanto a candidata estava defeituosa. Não é campanha comparativa.

Pacote local: `artifacts/a1-pilot-01/summary.json`, observações, identidades,
templates de restauração e `checksums.json`; exportação `artifacts/a1-pilot-01.zip`.
A configuração local com caminhos privados não integra a exportação. A aplicação,
imagens, manifests e evidências L4 permaneceram intactos. A cópia continua no mesmo
host; restauração independente de backup não foi verificada.

O bloqueio anterior da porta 52438 cessou após reinício do host: ela deixou a faixa
reservada do Windows e a API voltou a responder. O mesmo Kind foi utilizado, sem
novo cluster ou alteração de reservas do sistema. Não foi demonstrada relação causal
com trabalho em outra branch ou com uma atualização específica. O diagnóstico
anterior permanece em `artifacts/a1-preflight-01/`.

### A2 — Escopo escolhido e forma de execução

Comparar o acionamento explícito da restauração com o acionamento automático,
usando a mesma verificação A1, referência saudável e aplicação congelada. O detector
fica igual nas duas condições: avaliar recuperação e intervenção, sem alegar ganho
de detecção. Reutilizar ferramentas e contratos existentes, conforme DESIGN §8.5.
Não acrescentar Argo CD, HPA/KEDA, ACR ou workflow de deploy remoto a este aceite.

São dois incrementos, com commits por assunto na main, sem branches permanentes
por condição. Quando iniciada a execução A2, concluir ambos sequencialmente se os
critérios abaixo passarem; a transição técnica não exige uma rodada de aprovação
por arquivo ou ensaio. Esta atualização é apenas documental: nenhuma execução A2
foi realizada. Comandos novos só entram no guia operacional quando implementados.

### A2-I — Política de restauração e piloto integrado

1. Acrescentar o acionamento automático ao fluxo operacional, mantendo a interface
   explícita A1. Usar journal persistente, exclusão mútua, identidade, prazos e
   restauração restrita a `notifications-worker`; não reconstruir a aplicação.
2. Implementar o observador comum e resultados separados de candidata, cenário e
   recuperação. Conferir asserções por identidade, logs e consultas preservadas,
   além do veredito do executor.
3. Testar disparo correto e ausência de disparo em sucesso/inconclusão; configuração
   alterada por terceiro, contexto/UID incorretos, concorrência, falha de escrita,
   interrupção antes/depois do patch, resultado de envio desconhecido, timeout e
   falha da própria restauração. Retomada não repete mutações já confirmadas.
4. Executar quatro pilotos curtos no Kind real: duas condições × saudável/falha de
   startup. Restaurar a base entre tentativas. Não reutilizar resultados A1 na coleta.
   Correção de defeito gera evidência sucessora; não mudar a falha para obter vantagem.
5. Consolidar a configuração efetiva do protocolo abaixo, executáveis, imagem,
   prazos, relógios e coleta. Validar caminhos com espaços/PowerShell real, testes
   pertinentes, Ruff, documentos e CI Linux/Windows no SHA final.

**Aceite:** na falha confirmada, a política restaura uma vez e comprova o fluxo
completo; na saudável, não restaura indevidamente. Guardas recusam identidade
incorreta/inconclusão, e envio interrompido é reconciliado antes de mutação. Ambos
os procedimentos têm evidências comparáveis. Falha esperada continua sendo
implantação reprovada, mesmo após recuperação. Pilotos ficam fora da comparação.

### A2-II — Comparação delimitada e encerramento

Antes da primeira repetição, congelar o protocolo efetivo em artefato sanitizado
com hash, SHA executado e ordem completa. Aplicar o mesmo protocolo às duas
condições; não alterar critérios após observar a comparação.

| Item | Definição |
| --- | --- |
| Condições | R-explicita: veredito e comando separado de restauração; R-auto: mesma verificação e política DESIGN §8.5 |
| Cenários | Revisão saudável marcada; falha `DB_POOL_SIZE=0` apenas em `notifications-worker` |
| Amostra | Cinco pares por cenário, cada par com as duas condições: 20 tentativas previstas; pilotos excluídos |
| Ordem | Para cada cenário, alternar a primeira condição por par; inverter o início no segundo cenário. Fixar a lista antes da coleta |
| Ambiente | Mesmo Kind, host, imagens, réplicas, recursos e probes; sem builds/carga concorrente alheia. Não parar recursos de terceiros automaticamente |
| Base entre tentativas | Identidade saudável restaurada, ausência de pendências das tentativas anteriores e estado dos oito workloads conferido |
| Dados | IDs sintéticos novos por tentativa; sem apagar volumes/histórico. Registrar ordem e estado acumulado como limite, sem alegar independência estatística |
| Prazos iniciais | 90 s por rollout/fluxo, polling de 1 s e 600 s por tentativa incluindo recuperação; reservar prazo próprio para encerramento. Confirmar no piloto e congelar antes da coleta |
| Limite de execução | Até 4 h de janela comparativa, incluindo preparação e encerramento; reservar tempo para restaurar/parar. Não iniciar outra tentativa sem margem |

Registrar o ator do acionamento explícito e o intervalo entre detecção e comando.
Não impor atraso artificial. Quando executado por agente/script, apresentar como
acionamento explícito assistido, sem inferir tempo de reação humana ou produtividade.
Instrumentar também a condição explícita, mantendo sua restauração dependente
de comando separado. No cenário saudável, a limpeza final não conta
como recuperação automática nem integra o tempo de conclusão da candidata.

**Métricas:** decisão correta por cenário; restaurações indevidas; intervenções;
tempo de aplicação até detecção; intervalo detecção–solicitação de restauração;
tempo de solicitação até configuração saudável e até conclusão funcional. Registrar
também duração total e custo temporal da verificação saudável. Separar tempo técnico
de espera pelo acionamento. Não rotular essas medidas como MTBF/SLA de produção.

Fornecer tabela por tentativa e resumo por cenário/condição: contagens e denominadores,
mediana, mínimo/máximo e diferenças por par quando ambos forem comparáveis. Preservar
falhas, timeouts e inconclusões; não convertê-los em durações de sucesso, descartá-los
silenciosamente ou prometer significância estatística com cinco pares. Não juntar
cenários diferentes numa média única. A falha de startup não mede retomada de eventos
aceitos durante indisponibilidade; o evento posterior apenas comprova funcionamento.

Interromper na primeira falha inesperada ou limite de janela. Não substituir
repetições automaticamente. Corrigir defeitos pequenos com testes; se mudarem executor
ou protocolo após o início da coleta, preservar a série parcial e voltar ao piloto,
sem misturar SHAs/protocolos. Uma coleta incompleta termina com resultados parciais e
lacuna explícita; não iniciar rodadas sucessivas para completar a quota.

**Aceite e fechamento:** resultados rastreáveis, revisão saudável restaurada,
pendências classificadas, evidências exportadas com hashes e confirmação de leitura,
workloads/nó parados e dados preservados. Registrar separadamente entrega funcional
e comparação completa/incompleta. Atualizar README, plano e comandos, vinculando CI
ao SHA final. Cópia no mesmo host não é backup independente; não excluir dados para
encerrar. Nova pausa após A2; sem tag/release, B ou implantação Azure automática.

**Acionar o usuário somente se:** houver mudança de aplicação/stack/contrato,
necessidade de outro cenário/workload, custo/permissão novo, risco aos dados,
restauração malsucedida, bloqueio de ambiente ou coleta interrompida que exija nova
janela. Ausência de benefício da automação é resultado válido e não pede reparo.

## 8. Alternativa B — Autoescalonamento e processamento

**Proposta não aprovada.** Avaliar como uma política de autoescalonamento afeta
conclusão de trabalho, backlog e recuperação diante de variações controladas de
entrada, mantendo estável o procedimento de implantação.

Recorte possível: réplicas fixas versus uma política escolhida, aplicada a um
workload delimitado. Não comparar simultaneamente HPA, KEDA, todos os workers e
estratégias de deploy. Fixar capacidade dos nós inicialmente para distinguir
escala de pods de escala do cluster.

Preparação adicional: carga assíncrona que distinga oferecido/aceito/concluído,
backlog por etapa, idade da pendência e drain; métrica de escala compatível com
ACK antecipado e trabalho durável local; pools SQL, limites de réplicas e recursos
totais. Fila RabbitMQ vazia não é critério suficiente para reduzir a zero.
Manter ao menos um processador por serviço até existir recuperação demonstrada
para trabalho já retirado do broker.

Resultados possíveis: conclusão por segundo, latência de conclusão, idade/backlog,
tempo de recuperação, erros e consumo/custo. HTTP 202 rápido não comprova aumento
de capacidade; manter usuários virtuais iguais também não fixa a carga oferecida.
Polling e instrumentação entram na identidade do protocolo. Não exigir benefício
positivo para aceitar os resultados nem ajustar margem após observá-los.

## 9. Decisão e encerramento do ciclo

Decisão de 24/09/2026: concluir A2 em Kind, preservando A1 e a aplicação congelada.
O recorte concentra a avaliação no acionamento da restauração e sua confirmação
funcional. Não depende de vantagem de detecção, acesso ao AKS ou estudo de escala.
O protocolo e os dois incrementos estão na seção 7; os invariantes, no DESIGN §8.5.

| Decisão | Estado |
| --- | --- |
| Kind | Ambiente principal das duas condições A2; laboratório atualmente parado |
| A1 | Aceite congelado; não incorporar seus pilotos como repetições A2 |
| A2 | Escopo e plano definidos; implementação e coleta pendentes |
| B — Autoescalonamento | Extensão não selecionada |
| AKS/ACR | Extensão opcional, sem provisionamento, publicação de imagens ou gasto neste ciclo |
| Assinatura/região/cotas/custo Azure | Reavaliar somente se a extensão for escolhida; consultas não autorizam apply |
| Cópia independente/restauração de backup | Não verificadas; manter ressalva e dados preservados |
| Convite/acessos da equipe | Pendentes; não condicionam execução local assistida |
| Campanhas extensas da aplicação | Suspensas; separadas da comparação operacional A2 |
| Tag/release de infraestrutura | Não incluída nesta entrega |

Na pausa final, decidir encerrar com os resultados locais ou propor uma extensão
delimitada. Se houver verificação posterior no AKS, registrá-la separadamente:
ela não transforma medidas Kind em medidas de nuvem nem comprova equivalência.
Uma comparação no AKS exige executar ambas as condições ali; não comparar controle
local com procedimento automático na nuvem. Não abrir uma segunda campanha apenas
para compensar a indisponibilidade do serviço.
