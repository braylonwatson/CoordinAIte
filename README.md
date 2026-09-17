# CoordinAIte

CoordinAIte is an AI-powered football intelligence platform designed to assist defensive coordinators in making faster, more informed decisions during live gameplay. At its core, the application serves as a real-time decision-support tool that blends historical data with in-game context to predict offensive tendencies and recommend defensive strategies. The system was built with the goal of reducing reliance on intuition alone and instead providing coaches with data-driven insights that can be accessed instantly on the sideline.

The platform operates through an interactive dashboard where users input key situational variables such as down, distance, field position, time remaining, and score differential. Based on this information, the system uses a trained machine learning model to predict whether the offense is likely to run or pass. In addition to the prediction itself, the application provides probability distributions and confidence levels, allowing users to understand not just what the model predicts, but how certain it is. This added layer of interpretability is critical in high-pressure environments where decisions must be made quickly and with context.

Beyond simple prediction, CoordinAIte incorporates a live game tracking system that logs each play as it unfolds. After receiving a prediction, the user can input the actual result of the play, including the play type and yards gained. The system then records whether the prediction was correct and continuously updates performance metrics throughout the game. These metrics include overall accuracy, recent accuracy trends, and situational performance indicators such as third-down success and long-yardage scenarios. This allows users to evaluate both the model’s effectiveness and the evolving tendencies of the opposing offense in real time.

A key feature of the platform is its defensive strategy engine, which translates predictions into actionable recommendations. Rather than simply indicating run or pass, the system suggests specific defensive adjustments such as personnel groupings, front alignments, coverage shells, pressure schemes, and levels of aggression. These recommendations are accompanied by contextual reasoning, helping users understand why a particular strategy is being suggested. This transforms the tool from a passive predictor into an active assistant capable of guiding decision-making.

The application also includes user authentication and persistent storage features. Users can create accounts, log in securely, and save complete game states to a database. These saved sessions can later be resumed, allowing coaches or analysts to revisit previous games, review play logs, and continue analysis without losing progress. A guest mode is also available, enabling users to access the core prediction functionality without creating an account, though saving and history features are restricted to registered users.

From a technical standpoint, CoordinAIte is built using a modern full-stack architecture. The frontend is developed in React, featuring a responsive and visually consistent interface designed to work across both desktop and mobile devices. The backend is powered by FastAPI, which handles API requests, manages game state, and interfaces with the machine learning model. Data persistence is achieved through a PostgreSQL database using SQLAlchemy for object-relational mapping. The machine learning component utilizes an XGBoost classifier trained on NFL play-by-play data from recent seasons, incorporating both situational and contextual features to achieve approximately 70% prediction accuracy.

Looking forward, the project is designed with scalability and monetization in mind. The planned business model follows a freemium structure, where the current run/pass prediction functionality remains free, while advanced features such as play concept classification and directional prediction (left/right) are introduced in a paid subscription tier. This approach allows users to experience the core value of the product while creating a clear incentive to upgrade for deeper insights. Future expansions may include team-level subscriptions, opponent scouting reports, and enhanced analytics dashboards tailored for coaching staff and organizations.

Ultimately, CoordinAIte represents a step toward integrating artificial intelligence into real-time sports decision-making. By combining machine learning, live data tracking, and strategic recommendations, the platform aims to bridge the gap between analytics and on-field execution. The long-term vision is to evolve into a comprehensive defensive coordination assistant that not only predicts plays but also provides fully contextualized game strategies, empowering coaches to make smarter, faster, and more confident decisions.

## Production backend rebuild

The live API is now stateless: immutable XGBoost models are loaded once per API
process, while every game's mutable tracker state is persisted in PostgreSQL.
This allows Render to run multiple API instances without users sharing or losing
game state.

- [Architecture and design decisions](docs/architecture.md)
- [Database migration instructions](docs/database-migration.md)
- [Authentication, refresh cookies, and ownership](docs/authentication.md)

### Backend development

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m alembic -c alembic.ini upgrade head
python -m pytest -q
python -m uvicorn main:app --reload
```

Copy `.env.example` to `.env` and replace its example values locally. Never
commit `.env`.

For an existing setup, add the new variables without overwriting your `.env`.
`JWT_SECRET_KEY` is now required. Generate one random secret and keep it stable
across restarts and API instances. Local cookie authentication expects the
frontend at `http://localhost:3000` and `REACT_APP_API_URL=http://localhost:8000`.
See [the phase-two local setup steps](docs/phase2-local-setup.md) for the Windows
commands to apply this milestone to the working phase-one branch.

# AWS deployment

The backend can now be packaged as a container and deployed to ECS Fargate with
RDS PostgreSQL. See [the AWS deployment guide](docs/aws-deployment.md) for the
Terraform configuration, migration task, Vercel proxy, and GitHub Actions release
workflow. Cloud resources have not been provisioned by this code change.
