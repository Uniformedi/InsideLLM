{
  "realm": "${keycloak_realm_name}",
  "displayName": "InsideLLM",
  "displayNameHtml": "<strong>InsideLLM</strong> — SSO",
  "enabled": true,
  "sslRequired": "external",
  "registrationAllowed": false,
  "rememberMe": true,
  "loginWithEmailAllowed": true,
  "duplicateEmailsAllowed": false,
  "resetPasswordAllowed": true,
  "editUsernameAllowed": false,
  "bruteForceProtected": true,
  "accessTokenLifespan": 900,
  "ssoSessionIdleTimeout": 1800,
  "ssoSessionMaxLifespan": 36000,

  "groups": [
    {
      "name": "InsideLLM-View",
      "path": "/InsideLLM-View",
      "attributes": { "role": ["view"] },
      "realmRoles": ["view"]
    },
    {
      "name": "InsideLLM-Admin",
      "path": "/InsideLLM-Admin",
      "attributes": { "role": ["admin"] },
      "realmRoles": ["admin", "view"]
    },
    {
      "name": "InsideLLM-Approve",
      "path": "/InsideLLM-Approve",
      "attributes": { "role": ["approve"] },
      "realmRoles": ["approve", "view"]
    }
  ],

  "roles": {
    "realm": [
      { "name": "view",    "description": "Read-only access to InsideLLM services." },
      { "name": "admin",   "description": "Full admin across InsideLLM services."   },
      { "name": "approve", "description": "Approve pending governance changes."     }
    ]
  },

  "users": [
    {
      "username": "insidellm-admin",
      "enabled": true,
      "emailVerified": true,
      "firstName": "InsideLLM",
      "lastName": "Break-Glass",
      "email": "insidellm-admin@localhost",
      "credentials": [
        {
          "type": "password",
          "value": "${litellm_master_key}",
          "temporary": false
        }
      ],
      "groups": [
        "/InsideLLM-Admin",
        "/InsideLLM-Approve",
        "/InsideLLM-View"
      ],
      "realmRoles": ["admin", "approve", "view"]
    }
  ],

  "clients": [
    {
      "clientId": "governance-hub",
      "name": "InsideLLM Governance Hub",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "secret": "${keycloak_govhub_client_secret}",
      "redirectUris": [
        "https://${server_name}/governance/auth/callback",
        "https://${server_name}/governance/auth/callback/*"
      ],
      "webOrigins": ["https://${server_name}"],
      "attributes": {
        "post.logout.redirect.uris": "https://${server_name}/governance*"
      },
      "defaultClientScopes": ["openid", "profile", "email", "groups"],
      "optionalClientScopes": []
    },
    {
      "clientId": "open-webui",
      "name": "InsideLLM Open WebUI",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "secret": "${keycloak_owui_client_secret}",
      "redirectUris": [
        "https://${server_name}/oauth/oidc/callback",
        "https://${server_name}/*"
      ],
      "webOrigins": ["https://${server_name}"],
      "attributes": {
        "post.logout.redirect.uris": "https://${server_name}*"
      },
      "defaultClientScopes": ["openid", "profile", "email", "groups"],
      "optionalClientScopes": []
    },
    {
      "clientId": "litellm",
      "name": "InsideLLM LiteLLM Proxy",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "secret": "${keycloak_litellm_client_secret}",
      "redirectUris": [
        "https://${server_name}/litellm/sso/callback",
        "https://${server_name}/ui/*"
      ],
      "webOrigins": ["https://${server_name}"],
      "defaultClientScopes": ["openid", "profile", "email", "groups"],
      "optionalClientScopes": []
    }
  ],

  "clientScopes": [
    {
      "name": "groups",
      "description": "OIDC group membership claim (maps InsideLLM-* groups into the id_token)",
      "protocol": "openid-connect",
      "attributes": {
        "display.on.consent.screen": "true",
        "include.in.token.scope": "true",
        "consent.screen.text": "Access your group memberships"
      },
      "protocolMappers": [
        {
          "name": "groups-mapper",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-group-membership-mapper",
          "config": {
            "full.path": "false",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "userinfo.token.claim": "true",
            "claim.name": "groups"
          }
        }
      ]
    }
  ],

  "smtpServer": {},

  "eventsEnabled": true,
  "eventsExpiration": 2592000,
  "adminEventsEnabled": true,
  "adminEventsDetailsEnabled": true
}
