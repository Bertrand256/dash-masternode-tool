
# default "public" connections for RPC proxy
dashd_default_connections = [
    {
        'use_ssh_tunnel': False,
        'host': 'alice.dash-dmt.eu',
        'port': '8080',
        'username': 'dmtuser',
        'password': '674141414141425a4543753637714c4f79764f756d5673574466544b6e6f4e615a4733505a387132486e647773586c367646506631496a6d4b7a4d484c794448516454315f36714872525a77452d6b577369674c444550786b74554d704c667841673d3d',
        'use_ssl': True
    },
    {
        'use_ssh_tunnel': False,
        'host': 'luna.dash-dmt.eu',
        'port': '8080',
        'username': 'dmtuser',
        'password': '674141414141425a45437536667a3344745a50463570766d6c72616f6f454779626767314c33667857516e5f56666c3457574953664575435852684848507a7656774d536d3749365172384c6e647931624b6a33736a7033745073334e322d6c5a773d3d',
        'use_ssl': True
    },
    {
        'use_ssh_tunnel': False,
        'host': 'test.stats.dash.org',
        'port': '8080',
        'username': 'dashmnb',
        'password': '674141414141425a454375364c477053456746506a7759345166693547595574506330616550636c6e6f77426c36487276586a56345962494e527a79464e54676937716f6958706a6a377348387a32736d423271304d354e4f754a595449796a56413d3d',
        'use_ssl': True
    }
]
