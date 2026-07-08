# Deployment

One command per institute:

```bash
cd deploy
cp .env.example .env      # fill in POSTGRES_PASSWORD (access codes optional)
docker compose up --build
```

- Frontend: http://localhost:8080
- Backend API + OpenAPI docs: http://localhost:8000/docs
- Health: http://localhost:8000/health — must report `"pdb_instance": "test"`

## Safety

The stack ships pointing at the **PDB test instance** and nothing else.
There is no production URL in any file of this repository; a production
deployment would require deliberately setting `ITKFLOW_PDB_INSTANCE=production`
*and* `ITKFLOW_ALLOW_PRODUCTION=true` in the environment, which this compose
file does not do.
