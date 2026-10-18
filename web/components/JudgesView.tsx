"use client";

import type { EventRow } from "@/lib/api";

const REPO = "https://github.com/Vaibhaav-Tiwari/lineage";
const blob = (path: string) => `${REPO}/blob/main/${path}`;
const TOUR_QUESTION = "How does Python handle annotations under PEP 563, and who decided it?";
const CHANGE = "pep-563-superseded";

type Props = {
  events: EventRow[];
  applying: boolean;
  onAsk: (question: string) => void;
  onApply: (slug: string) => void;
  onReset: () => void;
  onOpen: (view: "ask" | "org" | "memory") => void;
};

/** A reading-room guide for judges: what Lineage is, a two-minute tour with buttons that do each step,
 *  what is real, where FalkorDB does the work, the numbers, and what went back upstream. */
export default function JudgesView({ events, applying, onAsk, onApply, onReset, onOpen }: Props) {
  const change = events.find((e) => e.slug === CHANGE);
  const applied = !!change?.applied;

  return (
    <main className="judges">
      <header className="judges-head">
        <h2>For Judges</h2>
        <p>
          Lineage is a company brain that remembers <em>why</em> it believes something, and un-learns when the truth
          changes. When a decision is reversed, every answer, belief, queued action and FAQ entry built on it is found
          through the graph and struck, marked stale, blocked or withdrawn.
        </p>
        <p className="judges-tracks">Tracks: Agent Memory &amp; Coordination, Company Brain. Built on FalkorDB 6.0.2.</p>
      </header>

      <div className="judges-grid">
        <section className="judges-tour" aria-labelledby="tour-h">
          <h3 id="tour-h">See it in two minutes</h3>
          <ol>
            <li>
              <p><strong>Ask about PEP 563</strong>, a real Python proposal that was later replaced. The answer has footnotes to the graph, and is saved as beliefs tied to that evidence.</p>
              <button className="btn" onClick={() => onAsk(TOUR_QUESTION)}>Ask it</button>
            </li>
            <li>
              <p><strong>Act on the answer.</strong> Under it, press <em>Queue: publish to the onboarding FAQ</em> and then <em>Run</em>: the action gate lets it through. Also queue <em>ask the owners to confirm</em>, but don&rsquo;t run that one yet.</p>
            </li>
            <li>
              <p><strong>Apply the real change:</strong> on 5 May 2025, PEP 563 was replaced by PEP 649 and PEP 749. This is the red pin on the timeline.</p>
              {applied ? (
                <p className="judges-note">
                  The change is already applied in this shared demo, by you or another visitor.{" "}
                  <button className="linkish" onClick={onReset}>Reset the demo</button> to start again from step 1.
                </p>
              ) : (
                <button className="btn" disabled={applying} onClick={() => onApply(CHANGE)}>{applying ? "Applying…" : "Apply the change"}</button>
              )}
            </li>
            <li>
              <p><strong>Watch it un-learn.</strong> The answer is struck through with the date, the belief goes stale, the FAQ entry is withdrawn, and the 8 proposals that cite PEP 563 get review tasks. Press <em>Run</em> on the action you queued: the Steward refuses and shows the chain of evidence that changed.</p>
            </li>
            <li>
              <p><strong>Look at the memory.</strong> Beliefs, now and at any earlier moment, the withdrawn FAQ entry, and 12 live checks proving each agent can only touch its own graphs.</p>
              <button className="btn quiet" onClick={() => onOpen("memory")}>Open Memory</button>
            </li>
            <li>
              <p><strong>Ask what would break.</strong> Who really maintains each module, the truck factor, an introduction path, and &ldquo;what if this person left?&rdquo; computed on a throwaway copy of the graph.</p>
              <button className="btn quiet" onClick={() => onOpen("org")}>Open Organisation</button>
            </li>
          </ol>
          <p className="judges-note">Everyone shares this one demo, and it resets every hour. <button className="linkish" onClick={onReset}>Reset it now</button></p>
        </section>

        <div className="judges-facts">
          <section aria-labelledby="real-h">
            <h3 id="real-h">What is real here</h3>
            <ul>
              <li>The data is the real Python project: 745 PEPs, 5,708 forum posts, 1,305 people and commit history since 2015, in one graph of 27,959 nodes and 67,601 relationships.</li>
              <li>The change is real: PEP 563&rsquo;s replacement, replayed from the forum post that announced it.</li>
              <li>This public demo answers <strong>without an LLM</strong>: sentences are composed from the graph evidence. The Claude-powered Historian runs locally (it uses a personal Claude Code login, which can&rsquo;t power a public site). Both score 20/20 on the evaluation.</li>
            </ul>
          </section>

          <section aria-labelledby="falkor-h">
            <h3 id="falkor-h">Where FalkorDB does the work</h3>
            <table className="judges-table">
              <thead><tr><th scope="col">FalkorDB feature</th><th scope="col">What it does here</th><th scope="col">See it in</th></tr></thead>
              <tbody>
                <tr><td>One graph per concern</td><td>the company archive, each agent&rsquo;s memory, your questions, a shared task board</td><td>Memory</td></tr>
                <tr><td>ACL logins and selectors, <span className="typed">ACL DRYRUN</span></td><td>each agent may touch only its own graphs; 12 checks prove it live</td><td>Memory</td></tr>
                <tr><td>Variable-length paths</td><td>the walk from a changed proposal to everything that rests on it</td><td>Ask, after the change</td></tr>
                <tr><td><span className="typed">GRAPH.COPY</span></td><td>&ldquo;what if this person left?&rdquo; runs on a throwaway fork</td><td>Organisation</td></tr>
                <tr><td>JavaScript UDF</td><td>recency of each person&rsquo;s commits, scored inside the query</td><td>Organisation</td></tr>
                <tr><td><span className="typed">algo.SPpaths</span>, <span className="typed">betweenness</span>, <span className="typed">WCC</span>, <span className="typed">labelPropagation</span>, <span className="typed">pageRank</span></td><td>introductions, bridge people, clusters, topic groups, importance</td><td>Organisation</td></tr>
                <tr><td>Vector and full-text indexes</td><td>hybrid search over PEP text and forum posts for open questions (Claude mode)</td><td><a href={blob("lineage/graph/search.py")} target="_blank" rel="noreferrer">search.py</a></td></tr>
                <tr><td>Unique and mandatory constraints</td><td>the database rejects malformed records</td><td><a href={blob("lineage/schema.py")} target="_blank" rel="noreferrer">schema.py</a></td></tr>
              </tbody>
            </table>
            <p className="judges-note">Every product query&rsquo;s median is under 3 ms server-side (<a href={blob("docs/benchmarks.md")} target="_blank" rel="noreferrer">benchmarks</a>).</p>
          </section>

          <section aria-labelledby="eval-h">
            <h3 id="eval-h">How we know it works</h3>
            <ul>
              <li>20 questions with answers from the real graph, including 3 the archive can&rsquo;t answer. Scored by code, not by an AI.</li>
              <li>Graph-only and Claude both: <strong>20/20</strong>, 100% citation recall, 3/3 correct refusals, and the change flags 8 of 8 expected proposals.</li>
              <li>A plain search engine over the same data scores <strong>10/20</strong>. It does show that a proposal was replaced; it can&rsquo;t fix what was already concluded from it.</li>
              <li>We wrote the questions ourselves, so this shows the system works, not general accuracy. <a href={blob("eval/results-graph-only.md")} target="_blank" rel="noreferrer">Results</a>, <a href={blob("eval/baseline.md")} target="_blank" rel="noreferrer">baseline</a>.</li>
            </ul>
          </section>

          <section className="judges-found" aria-labelledby="upstream-h">
            <h3 id="upstream-h">Found while building Lineage</h3>
            <p className="judges-found-lede">
              Building on FalkorDB 6.0.2 turned up two bugs nobody had reported yet. We reported both upstream, added
              what we learned to an existing crash report, and reviewed a docs change. Each report comes with a script
              that reproduces it in a throwaway container.
            </p>
            <ol className="finding-list">
              <li className="finding">
                <span className="finding-tag new">New issue</span>
                <p className="finding-what">The documented way to give a user read-only access to a graph refuses even reads.</p>
                <p className="finding-how">Hit while setting up, giving each agent read-only access to the company graph. ACL selectors work instead, and that is what Lineage uses.</p>
                <a href="https://github.com/FalkorDB/FalkorDB/issues/3356" target="_blank" rel="noreferrer">FalkorDB#3356</a>
              </li>
              <li className="finding">
                <span className="finding-tag new">New issue</span>
                <p className="finding-what">Replacing a JavaScript function library isn&rsquo;t atomic: a query that lands mid-reload fails with &ldquo;Unknown function&rdquo;.</p>
                <p className="finding-how">Found while stress-testing reloads during the crash hunt below. Lineage now reloads only when the code changed.</p>
                <a href="https://github.com/FalkorDB/FalkorDB/issues/3357" target="_blank" rel="noreferrer">FalkorDB#3357</a>
              </li>
              <li className="finding">
                <span className="finding-tag added">Added to an existing issue</span>
                <p className="finding-what">One ordinary read query, grouped a certain way, takes the whole server down.</p>
                <p className="finding-how">It crashed our server twice while benchmarking. It was already reported, so we added a minimal reproduction and which query shapes do and don&rsquo;t trigger it.</p>
                <a href="https://github.com/FalkorDB/FalkorDB/issues/3150#issuecomment-6215167947" target="_blank" rel="noreferrer">Our comment on FalkorDB#3150</a>
              </li>
              <li className="finding">
                <span className="finding-tag review">Docs review</span>
                <p className="finding-what">A new &ldquo;read-only&rdquo; example in the docs can still write, because profiling a query runs it.</p>
                <p className="finding-how">Spotted while testing that pull request&rsquo;s examples: the user could create and delete data.</p>
                <a href="https://github.com/FalkorDB/docs/pull/456#issuecomment-6216303368" target="_blank" rel="noreferrer">Our review on docs#456</a>
              </li>
            </ol>
          </section>

          <section aria-labelledby="limits-h">
            <h3 id="limits-h">Limits</h3>
            <ul>
              <li>Python&rsquo;s record is unusually clean: formal statuses and &ldquo;superseded by&rdquo; links. Lineage doesn&rsquo;t yet learn decisions from messy chat.</li>
              <li>One organisation, no connectors, one replayable change.</li>
            </ul>
          </section>

          <section aria-labelledby="links-h">
            <h3 id="links-h">Read more</h3>
            <ul className="judges-links">
              <li><a href={REPO} target="_blank" rel="noreferrer">Code on GitHub</a></li>
              <li><a href={`${REPO}#readme`} target="_blank" rel="noreferrer">README: design, data model, queries</a></li>
              <li><a href={blob("docs/upstream/README.md")} target="_blank" rel="noreferrer">The FalkorDB findings in full</a></li>
              <li><a href={blob("docs/deploy.md")} target="_blank" rel="noreferrer">How this demo is deployed</a></li>
            </ul>
          </section>
        </div>
      </div>
    </main>
  );
}
