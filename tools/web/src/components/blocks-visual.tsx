// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export function BlocksVisual() {
  return (
    <div
      className="blocks-visual"
      role="img"
      aria-label="Illustration of beginner blocks generating readable MicroPython"
    >
      <div className="blocks-visual__toolbar">
        <span />
        <span />
        <span />
        <b>Blocks</b>
      </div>
      <div className="blocks-visual__body">
        <div className="blocks-stack" aria-hidden="true">
          <div className="code-block code-block--event">
            when program starts
          </div>
          <div className="code-block code-block--setup">
            set pin <b>2</b> to output
          </div>
          <div className="code-block code-block--loop">repeat forever</div>
          <div className="code-block code-block--action">
            <span>set pin 2</span>
            <b>HIGH</b>
          </div>
          <div className="code-block code-block--time">
            wait <b>0.5</b> seconds
          </div>
          <div className="code-block code-block--action">
            <span>set pin 2</span>
            <b>LOW</b>
          </div>
        </div>
        <div className="blocks-python" aria-hidden="true">
          <span className="blocks-python__label">PYTHON</span>
          <pre>
            <code>
              <em>from</em> machine <em>import</em> Pin{"\n"}
              <em>from</em> time <em>import</em> sleep{"\n\n"}
              led = Pin(<strong>2</strong>, Pin.OUT){"\n"}
              <em>while</em> <strong>True</strong>:{"\n"}
              {"    "}led.value(<strong>1</strong>){"\n"}
              {"    "}sleep(<strong>0.5</strong>){"\n"}
              {"    "}led.value(<strong>0</strong>)
            </code>
          </pre>
        </div>
      </div>
    </div>
  );
}
