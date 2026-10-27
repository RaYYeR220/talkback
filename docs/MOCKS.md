# Real and simulated

| Part | Real | Simulated |
|---|---|---|
| Football data | — | Everything: league, clubs, players, careers, season so far, every match event and tracking frame comes from our generator and engine |
| Models | Foundry deployments for every agent in the deployed gallery and the evaluation of record | A scripted chat client is used only inside the automated tests |
| Hosted agents | The Archivist and the Lab run as Foundry hosted agents over A2A v1.0 | In local runs and tests they run in process or on a local A2A server |
| Event feed | Azure Event Hubs, one partition per match, written by the generator job | Local runs replay the same items from disk |
| Content Safety | Azure AI Content Safety on every line in the deployment | Local development (`TALKBACK_ENV=dev`) skips it and says so in the verdict reasons |
| Broadcast graphics | EBU OGraf v1 graphics driven through the OGraf Server API; renderer pages in the browser | No hardware vision mixer or playout server is connected |
| Producer | A person pressing approve or reject in the console during a live run | In the public replay the decisions were made during the recorded run; unanswered holds expire as not aired |
| Territory packs | Code-enforced rules | The rules are illustrative templates written for this project, not any broadcaster's or regulator's actual policy |
| Time | Live runs play the matchday faster than real time | Line lifetimes and latencies are measured in wall time, as a live broadcast would see them |
