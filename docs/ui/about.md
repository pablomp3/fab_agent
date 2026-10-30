## The problem: the 2 AM alarm

A **fab** (a semiconductor factory) runs hundreds of **tools** — individual
machines such as etchers, deposition chambers, and ion mills. Each tool logs
dozens of sensors: coolant flow, chamber pressure, RF power. Silicon **wafers**
(the discs that chips are built on, hundreds of chips each) move between tools
in **lots** of about 25, and each tool processes them with a fixed set of
settings called a **recipe**.

When a tool raises an alarm, the on-call engineer exports its sensor log and has
minutes to decide: is this a **real hardware fault**, a **broken sensor**, a
**knock-on effect** of something upstream, or **normal behaviour** that only
looks odd?

- **Acting on a broken sensor is expensive.** Opening the machine or changing
  its recipe because one faulty sensor spiked stops the tool for hours.
- **Missing a real fault is worse.** Every lot that passes through a faulty tool
  afterwards can be ruined (*scrapped*).
- **The evidence is hard to hold together.** Dozens of sensors, missing columns,
  and sensors that contradict each other. A chatbot will still answer
  confidently.

Unplanned downtime and a scrapped lot are both expensive; the exact cost depends
on the fab and the process.

**FabAgent turns that sensor log into one defensible next step** — or says
plainly that the data is not enough.

> **NVIDIA Nemotron reasons. Tavily researches. Python checks. The engineer decides.**

---

## Why it needs both AI and Python

| Approach alone | Where it breaks |
|---|---|
| **A chatbot** | On our benchmark, a frontier model sent someone to inspect hardware when a required sensor was missing; another only escalated and rarely named a cause. Nothing stops a chatbot from suggesting a recipe change. |
| **Fixed rules** | Safe on machines someone already described, but they need a manual mapping and a hand-written model, and they cannot challenge their own conclusion. |

FabAgent uses **NVIDIA Nemotron** for the reasoning work — mapping a machine
nobody has described yet, proposing causes, and challenging its own leading
cause — and **Python** for the decision, which the model cannot override.

---

## What you get

| Result | What it means | What to do |
| --- | --- | --- |
| **Fault Confirmed** | The sensors match a known fault pattern. | Inspect the named part. |
| **Regular Behavior** | Every checked sensor is normal. | Keep monitoring. |
| **Sensors Disagree** | One sensor moved, but the sensors that should move with it did not — usually a faulty sensor, not a faulty machine. | Check the sensor first. |
| **Data Incomplete** | A sensor needed for the decision is missing from the file. | Get the missing data. |
| **Needs Review** | The data is not enough to confirm or rule out a cause. | Ask an engineer to review. |
| **Unknown Machine** | No saved description of this machine matches the file; the column meanings are AI guesses. | Review the guessed columns. |

Every result comes with a next step, a plain-language reason, and an audit
trail. With a saved tool model, the same file always gives the same answer;
Auto-mode drafts stay **Unknown Machine** until an engineer reviews them.

---

## Who it is for

| Person | What is expensive today | What FabAgent changes |
| --- | --- | --- |
| **On-call / junior engineer** | Dozens of sensor charts, an unfamiliar alarm, no clear next step | One plain result, one safe action, and the sensors behind it |
| **Senior process engineer** (owns the tool's recipes) | AI advice they cannot audit or correct | An editable tool model, visible checks, and a full audit trail |
| **Fab operations manager** | Hours lost to false alarms; scrap from wrong fixes | Sensor faults caught before anyone opens the machine; missing data stops the run instead of driving a guess |

Semiconductor fabs are the first target because a wrong call costs the most
there. The same workflow applies to any factory machine that exports sensor
data — injection moulding, industrial robots, energy equipment.

---

## Hard limits, enforced in code

These are not policy promises. They are properties of the code:

- **The action field cannot represent a recipe change or lot hold.** It is a
  fixed list — inspect the part, keep monitoring, ask an engineer, get more data,
  check the sensor, or review the guessed columns.
- **It cannot promote a model guess into a fault.** A cause proposed by NVIDIA
  Nemotron without a saved check is **Needs Review**, never **Fault Confirmed**.
- **It cannot outvote a contradiction.** If a sensor moves and the sensors that
  should move with it stay flat, the result is **Sensors Disagree**.
- **It cannot hide missing data.** A required sensor that is absent becomes
  **Data Incomplete**.
- **It cannot send raw sensor data to the model.** Only a statistical summary
  under 2 KB crosses the network, and every citation is re-checked by Python.
- **It cannot confirm a fault while a large movement is unexplained.** Any
  unexplained sensor at or above 5 robust z (normal-equivalent sigma) blocks a
  bare **Fault Confirmed**.
