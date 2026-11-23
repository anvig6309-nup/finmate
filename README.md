 🪙 FINMATE: The "Pocket CA"
### *An Intelligent, Proactive Personal Financial Manager & Decision Support System*
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg?logo=sqlite&logoColor=white)](https://sqlite.org)
[![Chart.js](https://img.shields.io/badge/UI-Chart.js%20%7C%20Dark%20Theme-FF6384.svg?logo=chartdotjs&logoColor=white)](https://www.chartjs.org/)
[![Status](https://img.shields.io/badge/Status-Active%20Development-success.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()
---
> **"Traditional finance trackers ask: *'Where did my money go?'***  
> **FinMate empowers you to ask: *'How should I use my money next?'"***
**FinMate** is an intelligent personal finance manager and digital "Pocket Chartered Accountant (CA)" designed to solve the cognitive and behavioral challenges of personal finance. Rather than just recording historical transactions retrospectively, FinMate pairs **behavioral economics (Nudge Theory)**, **forward-looking predictive cash-flow forecasting**, and **interactive decision simulators** to guide users *before* they spend.
---
## 📑 Table of Contents
- [Why FinMate?](#-why-finmate)
- [Psychological & Behavioral Foundation](#-psychological--behavioral-foundation)
- [Comprehensive Feature Showcase](#-comprehensive-feature-showcase)
  - [1. "Can I Afford This?" (Affordability Checker)](#1--can-i-afford-this-real-time-affordability-checker)
  - [2. "What-If" Scenario Simulator & Time Machine](#2--what-if-scenario-simulator--time-machine)
  - [3. Predictive Cash-Flow Engine & Shortage Forecast](#3--predictive-cash-flow-engine--shortage-forecast)
  - [4. Smart 50/30/20 Budget Planner & Burn-Rate Tracker](#4--smart-503020-budget-planner--burn-rate-tracker)
  - [5. Milestone-Based Goal Locker & Pacing Engine](#5--milestone-based-goal-locker--pacing-engine)
  - [6. Gamified Habit Formation & Behavioral Nudges](#6--gamified-habit-formation--behavioral-nudges)
  - [7. Interactive Visual Fintech Dashboard](#7--interactive-visual-fintech-dashboard)
  - [8. India-Specific & Regional Roadmap](#8--india-specific--regional-roadmap)
- [Competitive Matrix: FinMate vs. Traditional Apps](#-competitive-matrix)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Project Directory Structure](#-project-directory-structure)
- [Quick Start & Setup Guide](#-quick-start--setup-guide)
- [API Endpoints Overview](#-api-endpoints-overview)
- [Research & Academic Attribution](#-research--academic-attribution)
## 5. 🎯 Milestone-Based Goal Locker & Pacing Engine
* **Goal Setting with Deadlines**: Create defined milestones (e.g., *"Emergency Fund - ₹50,000"*, *"Goa Trip - ₹20,000"*).
* **Automated Monthly Requirement**: Computes required savings velocity:
  $$\text{Monthly Needed} = \frac{\text{Target Amount} - \text{Saved Amount}}{\text{Months Remaining}}$$
* **Capital Protection**: When you contribute funds to a goal, FinMate marks the amount as locked capital. This ensures that money committed to long-term goals is never shown as safe-to-spend for impulse purchases.
---
### 6. 🎮 Gamified Habit Formation & Behavioral Nudges
* **Streaks & Consistency**: Encourages daily budget adherence and healthy logging streaks.
* **Positive Reinforcement**: Celebration milestones when reaching 25%, 50%, 75%, and 100% of saving targets.
* **Contextual Nudges**: Smart alerts when spending velocity exceeds historical averages.
---
### 7. 💻 Interactive Visual Fintech Dashboard
FinMate comes with a responsive, dark-mode visual interface (`visual.html`) built with **Chart.js**:
* 📈 **Spending Breakdown Doughnut Chart**: Instant visual understanding of your expense distribution.
* 📊 **Budget vs. Actual Spent Bar Chart**: Visual comparison of budget limits against current burn per category.
* ⚡ **Live Key Performance Indicators (KPIs)**:
  * Available Funds
  * Monthly Inflow & Outflow
  * Safe Daily Spend
* 🎯 **Live Goal Progress Bars**: Interactive progress bars with one-click fund contribution.
* 📝 **Real-Time Transaction Feed**: Quick-entry form for rapid income and expense recording.
---Transaction Logging** | ✅ (Reactive / SMS based) | ✅ (Manual) | ✅ Real-time & Automated |
| **Where Did My Money Go?** | ✅ Yes | ✅ Yes | ✅ Comprehensive |
| **"Can I Afford This?" Checker** | ❌ No | ❌ No | ✅ **Yes (Instant Verdict)** |
| **"What-If" Scenario Simulator** | ❌ No | ❌ No | ✅ **Yes (Interactive Sandbox)** |
| **Forward Cash-Flow Forecasting**| ❌ No | ❌ No | ✅ **Yes (30-90 Day Timeline)** |
| **Safe Daily Spend Metric** | ❌ No | ❌ No | ✅ **Yes (Auto-updating)** |
| **Goal Protection Mechanism** | ⚠️ Partial (Isolated) | ⚠️ Manual allocation | ✅ **Yes (Deducted from Safe Pool)** |
| **Behavioral Nudge Engine** | ❌ Generic Ads / Loans | ❌ Basic | ✅ **Yes (Nudge Theory Rooted)** |
| **Privacy & Local Ownership** | ❌ Cloud Synced / Ad-Driven | ⚠️ Proprietary Cloud | ✅ **Yes (Local-first / Transparent)** |
---
## 🏗️ System Architecture
```mermaid
flowchart TD
    subgraph UI ["Frontend / Presentation Layer"]
        A[Modern Dark Dashboard visual.html]
        B[Chart.js Visualizations: Pie & Bar]
        C[Affordability & What-If Controls]
    end
    subgraph API ["FastAPI Application Layer"]
        D[auth.py: JWT Auth & User Sessions]
        E[routes_core.py: Funds, Categories, Dashboard]
        F[routes_planner.py: 50/30/20 Budget, Goals, Demo Seeder]
        G[logic.py: Mathematical Forecast & Affordability Engine]
    end
    subgraph Data ["Data & Persistence Layer"]
        H[(SQLite Database finmate.db)]
        I[models.py: SQLAlchemy Models]
    end
    A <-->|REST API JSON + Bearer Token| API
    B <-->|Render Data| API
    C <-->|Query Scenarios| G
    API <-->|SQLAlchemy ORM| I
    I <-->|Store / Query| H
| `POST` | `/auth/login` | Authenticate and obtain JWT access token |
| `GET` | `/me` | Get current user profile and onboarding status |
| `POST` | `/onboarding` | Save monthly income & baseline starting funds |
| `GET` | `/funds` | Retrieve starting funds and calculated available balance |
| `GET` | `/categories` | Fetch active user categories and monthly limits |
| `POST` | `/categories` | Update category list and budget thresholds |
| `GET` | `/dashboard` | Aggregated dashboard: funds, monthly stats, category totals, recent history |
| `GET` | `/budget/plan` | 50/30/20 rule breakdown based on monthly income |
| `GET` | `/budget/status` | Real-time budget consumption, status flags (`ok`/`warning`/`over`), and safe daily spend |
| `GET` | `/goals` | List all active savings goals with progress % and monthly required savings |
| `POST` | `/goals` | Create a new target-oriented savings goal |
| `POST` | `/goals/{id}/contribute`| Deposit funds into a goal (transfers money to locked savings) |
| `POST` | `/demo/seed` | Seed realistic demo transactions, categories, and goals |
Interactive Swagger documentation is available out of the box at **`http://127.0.0.1:8000/docs`**.
---
## 🎓 Research & Academic Attribution
FinMate was conceptualized as a research-backed initiative bridging behavioral finance and AI-driven decision support systems:
* **Title**: *FinMate: An Intelligent Personal Financial Manager — The "Pocket CA"*
* **Researchers**: Anvi Gupta, Bhoomi Agrawal, Anvi Singh Chauhan
* **Faculty Advisor**: Ms. Meenakshi Jalandra
* **Core Academic Domains**: Behavioral Economics (Nudge Theory), Machine Learning in FinTech, Decision Support Systems (DSS), Financial Gamification.
### Key References
1. **R. H. Thaler and C. R. Sunstein**, *Nudge: Improving Decisions About Health, Wealth, and Happiness*. Yale University Press, 2008.
2. **S. Gupta and P. Arora**, *"Personal Finance Management Applications: A Comparative Study,"* *International Journal of Information Management*, vol. 57, pp. 102–118, 2021.
3. **A. Jain and R. Kumar**, *"AI-Driven Financial Advisory Systems: A Review,"* *Journal of Financial Technology Research*, vol. 12, no. 3, pp. 45–59, 2020.
4. **J. Hamari, J. Koivisto, and H. Sarsa**, *"Does Gamification Work? A Literature Review of Empirical Studies on Gamification,"* in *Proc. 47th Hawaii Int. Conf. System Sciences (HICSS)*, 2014.
5. **D. J. Power**, *Decision Support Systems: Concepts and Resources for Managers*. Greenwood Publishing Group, 2002.
---
<p align="center">
  <b>Built with ❤️ by the FinMate Team</b><br>
  <i>Empowering students and young professionals toward proactive financial freedom.</i>
</p>
