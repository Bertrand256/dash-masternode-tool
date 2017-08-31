## Proposals: browsing and voting on

Version 0.9.8 of the application has introduced the functionality of reviewing of current proposals with the ability to cast votes by *masternode owners*. In addition to MNOs, this feature is also dedicated to *proposal owners* who can use it to track and analyze the progress of voting on their proposals.


To use these features, open the *Proposals* window by clicking the `Tools->Proposals...` menu item in the main application window. As a result, the following window will appear:  
![1](img/dmt-proposals-window.png)

The first start of the window takes up to a few minutes, during which the application retrieves data of all of the proposals currently maintained by the network along with the votes casted on them by masternodes. That data is then saved to a db-cache, so the next start of the window should be much faster.

The upper part of the window shows a proposal table with several selected attributes, displayed in its columns. Attributes less significant are initially hidden, but can be turned on withing the *Columns* dialog. In addition to turning column on/off, you can also change their order.  
![1](img/dmt-proposals-columns.png)

Within the *Proposals* dialog you can:
 * view the list of all of the currently available proposals along with their details
 * view the list of votes casted on particular proposal by masternodes
 * cast a vote on proposals (if the user has a masternode configured)
 * save the proposals and votes data to a CSV files for further analysis
 * view charts showing the voting process 


### Reviewing the proposal details
All the most important details of the proposal can be viewed on the *Details* tab (look at the screenshot above).

### Reviewing the voting details
Go to the *Voting History* tab, where you can view:
 * a list of all votes along with the vote date/time and voting masternode 
 * a chart of incremental count of votes by date
 * a chart of vote-changes by date (during the voting period MNO can change vote at any time)
 * a summary chart of YES, NO, ABSTAIN votes count  
 
![1](img/dmt-proposals-voting-history.png)

Vote-change chart:  
![1](img/dmt-proposals-vote-change-chart.png)

Votes summary chart:  
![1](img/dmt-proposals-vote-summary-chart.png)
 
### Casting vote
Open the *Vote* tab in the botom part of the *Proposals* window. It will show one row of voting buttons (*Yes*, *No*, *Abstain*) for each masternode registered in the application and in addition one row of buttons dedicated to voting on behalf of all of the user's masternodes:  
![1](img/dmt-proposals-vote.png)  

#### Privacy!!!  
If you own several or more masternodes, you should take into account the fact, that voting on their behalf at the same moment is like you announced to the world, that they all have one owner, which is not a good thing from a privacy point of view. Look at the screenshot below:   
![1](img/dmt-proposals-vote-time-offset.png)  
Bear in mind, that all these informations are available to anybody who have access to any Dash daemon.

Fortunately, there is an easy way to mitigate this. Application can add a random offset (from the range +/- 30 min) to the voting-time for each of the voting masternodes, so clicking the `Yes/No/Abstain for All` buttons will result in different voting-time for each of your masternodes seen in the network thereafter. This feature is controlled by a dedicated configuration option as can be seen on the screenshot below:  
![1](img/dmt-proposals-config-time-offset.png)